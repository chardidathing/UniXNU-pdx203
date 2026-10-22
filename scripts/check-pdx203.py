#!/usr/bin/env python3
"""preflight of the pdx203 firmware port, run before the edk2 build (unixnu build firmware, or by hand).

checks the device package against the stock kona dtb set of the sony boot image and against its own configuration:
every fixed /reserved-memory node is a reserved descriptor of the memory map, the descriptors are page aligned and do not
overlap, the fd and stack of the config and dsc are in the map, the splash buffer geometry fits the splash carve-out and the
pingpong the panel kick uses is the first one the dtb lists. vendor inputs (Binaries/pdx203) are only listed, the default
build does not use them.

the mu-silicium checkout is found through --uefi, UNIXNU_UEFI, this script's own repository, or ./uefi-pdx203.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import tomllib
from pathlib import Path

PACKAGE = Path('Platforms/Sony/pdx203Pkg')
DTB = Path('Resources/DTBs/pdx203.dtb')
CONFIG = Path('Resources/Configs/pdx203.toml')


def find_uefi(arg):
    candidates = [arg, os.environ.get('UNIXNU_UEFI'), Path(__file__).resolve().parents[1], Path('uefi-pdx203')]
    for candidate in candidates:
        if candidate and (Path(candidate) / PACKAGE / 'pdx203.dsc').is_file():
            return Path(candidate).resolve()
    raise SystemExit('no mu-silicium checkout with Platforms/Sony/pdx203Pkg, give --uefi or set UNIXNU_UEFI')


def split_dtbs(data):
    """the sony boot image carries one dtb per soc revision back to back, the loader picks one."""
    parts = []
    offset = 0
    while offset + 8 <= len(data):
        magic, total = struct.unpack('>II', data[offset:offset + 8])
        if magic != 0xD00DFEED:
            raise SystemExit(f'not a dtb at offset {offset:#x}')
        parts.append(data[offset:offset + total])
        offset += total
    return parts


def fdtget(path, node, prop, kind='x'):
    result = subprocess.run(['fdtget', '-t', kind, str(path), node, prop], capture_output=True, text=True)
    if result.returncode:
        return None
    return result.stdout.split()


def fdt_list(path, node):
    result = subprocess.run(['fdtget', '-l', str(path), node], capture_output=True, text=True)
    return result.stdout.split() if result.returncode == 0 else []


def reservations(path):
    found = []
    for node in fdt_list(path, '/reserved-memory'):
        cells = fdtget(path, f'/reserved-memory/{node}', 'reg')
        if not cells:
            continue   # dynamic carve-outs, linux places them at runtime
        values = [int(v, 16) for v in cells]
        for index in range(0, len(values), 4):
            base = (values[index] << 32) | values[index + 1]
            size = (values[index + 2] << 32) | values[index + 3]
            found.append((node, base, size))
    return found


def memory_rows(source):
    pattern = r'\{"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+),([^}]+)\}'
    return [(m[1], int(m[2], 16), int(m[3], 16), m[4]) for m in re.finditer(pattern, source)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uefi', help='mu-silicium checkout with the pdx203 package')
    parser.add_argument('--report', help='json report path (default: build/pdx203/check.json when build/ exists)')
    args = parser.parse_args()
    uefi = find_uefi(args.uefi)
    package = uefi / PACKAGE
    errors = []
    notes = []

    rows = memory_rows((package / 'Library/MemoryMapLib/MemoryMapLib.c').read_text())
    if not rows or len(rows) > 128:
        errors.append('empty map or descriptor capacity exceeded')
    for name, base, size, _ in rows:
        if base % 4096 or size % 4096 or not size:
            errors.append(f'not page aligned: {name}')
    # register regions may nest (the imem cookie page sits inside the imem window), the firmware only checks ddr for overlap
    ddr = [row for row in rows if row[1] >= 0x80000000]
    for index, (name, base, size, _) in enumerate(ddr):
        for other, other_base, other_size, _ in ddr[index + 1:]:
            if max(base, other_base) < min(base + size, other_base + other_size):
                errors.append(f'overlapping descriptors: {name}, {other}')

    # every fixed carve-out of every dtb in the set must be a reserved descriptor with the same extent
    scratch = Path(os.environ.get('TMPDIR', '/tmp')) / f'check-pdx203-{os.getpid()}'
    scratch.mkdir(parents=True, exist_ok=True)
    dtbs = split_dtbs((uefi / DTB).read_bytes())
    splash = None
    pingpong = None
    checked = 0
    for index, blob in enumerate(dtbs):
        path = scratch / f'{index}.dtb'
        path.write_bytes(blob)
        model = subprocess.run(['fdtget', str(path), '/', 'model'], capture_output=True, text=True).stdout.strip()
        for node, base, size in reservations(path):
            checked += 1
            if not any(a == base and s == size and re.search(r'\bReserv\b', attrs) for _, a, s, attrs in rows):
                errors.append(f'dtb {index} ({model}): carve-out {node} {base:#x}+{size:#x} is not a reserved descriptor')
            if node.startswith('cont_splash_region'):
                splash = (base, size)
        mdss = next((n for n in fdt_list(path, '/soc') if n.startswith('qcom,mdss_mdp@')), None)
        if mdss:
            offsets = fdtget(path, f'/soc/{mdss}', 'qcom,sde-pp-off')
            if offsets:
                pingpong = int(mdss.split('@')[1], 16) + int(offsets[0], 16)
    for path in scratch.glob('*.dtb'):
        path.unlink()
    scratch.rmdir()

    config = tomllib.loads((uefi / CONFIG).read_text())
    fd = config['uefi_fd']
    if not any(n == 'UEFI FD' and a == fd['base'] and s == fd['size'] for n, a, s, _ in rows):
        errors.append('fd configuration does not match the "UEFI FD" descriptor')
    if fd['size'] % 4096:
        errors.append('fd size is not a whole number of 4 KiB blocks')
    if not config.get('boot_shim', {}).get('requires_kernel_header', False):
        errors.append('the loader needs the arm64 image header in front of the shim')
    image = config.get('boot_image', {})
    if image.get('header_version', 0) >= 2 and not image.get('dtb'):
        errors.append('a header v2 boot image needs the dtb section (boot_image.dtb)')

    dsc = (package / 'pdx203.dsc').read_text()
    stack = re.search(r'PcdCPUCoresStackBase\|(0x[0-9a-fA-F]+)', dsc)
    if not stack or not any(n == 'UEFI Stack' and a == int(stack[1], 16) for n, a, _, _ in rows):
        errors.append('stack configuration does not match the "UEFI Stack" descriptor')

    width = int(re.search(r'PcdFrameBufferWidth\|(\d+)', dsc)[1])
    height = int(re.search(r'PcdFrameBufferHeight\|(\d+)', dsc)[1])
    depth = int(re.search(r'PcdFrameBufferColorDepth\|(\d+)', dsc)[1])
    display = next(((a, s) for n, a, s, _ in rows if n == 'Display Reserved'), None)
    if display is None:
        errors.append('no "Display Reserved" descriptor, SimpleFbDxe and the sec log need it')
    else:
        if splash and display != splash:
            errors.append(f'"Display Reserved" {display[0]:#x}+{display[1]:#x} is not the cont_splash_region {splash[0]:#x}+{splash[1]:#x}')
        if width * height * depth // 8 > display[1]:
            errors.append('the frame buffer geometry does not fit the splash carve-out')

    configured = re.search(r'PcdMdpPingPongBase\|(0x[0-9a-fA-F]+)', dsc)
    if not configured:
        errors.append('no PcdMdpPingPongBase, the command mode panel freezes on the splash without the kick')
    elif pingpong is None:
        notes.append('dtb has no qcom,sde-pp-off, the pingpong base is unchecked')
    elif int(configured[1], 16) != pingpong:
        errors.append(f'PcdMdpPingPongBase {configured[1]} is not the first pingpong of the dtb ({pingpong:#x})')

    dependencies = set()
    for inc in (package / 'Include').glob('*.inc'):
        dependencies.update(re.findall(r'Binaries/pdx203/[^\s}]+', inc.read_text()))
    missing = sorted(p for p in dependencies if not (uefi / p).is_file())
    vendor = re.search(r'PDX203_VENDOR_HW\s*=\s*(\d)', dsc)
    if vendor and vendor[1] == '1' and missing:
        errors.append(f'PDX203_VENDOR_HW = 1 but {len(missing)} vendor inputs are missing')

    result = {'uefi': str(uefi), 'descriptors': len(rows), 'dtbs': len(dtbs), 'carveouts_checked': checked,
              'static_errors': errors, 'notes': notes, 'missing_vendor_inputs': missing,
              'vendor_hw_enabled': bool(vendor and vendor[1] == '1'),
              'runtime_ram_verified': False, 'hardware_boot_demonstrated': False}
    report = Path(args.report) if args.report else (Path('build/pdx203/check.json') if Path('build').is_dir() else None)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + '\n')
    print(f'{checked} carve-outs of {len(dtbs)} dtbs checked against {len(rows)} descriptors')
    print(f'{len(errors)} static errors, {len(missing)} vendor inputs absent (unused with PDX203_VENDOR_HW = 0), hardware unverified')
    for line in errors + notes:
        print(line)
    sys.exit(bool(errors))


if __name__ == '__main__':
    main()
