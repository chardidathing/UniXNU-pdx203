#!/usr/bin/env python3
"""compile package/Pdx203Stubs.c with the kernel's own c flags into build/pdx203-stubs/libPdx203Stubs.a.

the defconfig names the archive in CONFIG_XNU_EXTRA_LD_ARCHIVES, the base link script appends it as is.
"""
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/pdx203-stubs'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # any c compile record of the kernel pass carries the flags, this one is the record the driver itself waits for
    record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json').read_text().strip().rstrip(','))
    source = ROOT / 'kits/pdx203/Pdx203Stubs.c'
    obj = OUT / 'Pdx203Stubs.o'
    command, index = [], 0
    arguments = record['arguments']
    while index < len(arguments):
        value = arguments[index]
        if value == record['file']:
            command.append(str(source))
        elif value in ('-o', '-MF', '-MT', '-MJ'):
            if value == '-o':
                command += ['-o', str(obj)]
            index += 1
        elif value == '-Xclang' and arguments[index + 1].startswith('-W'):
            index += 1
        elif not value.startswith('-W'):
            command.append(value)
        index += 1
    command += ['-Wall', '-Wextra', '-Werror']
    subprocess.run(command, cwd=record['directory'], check=True)
    magic, cpu, subtype, kind = struct.unpack_from('<4I', obj.read_bytes())
    if (magic, cpu, subtype, kind) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit('build-pdx203-stubs: not an arm64 object')
    archive = OUT / 'libPdx203Stubs.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(obj)], check=True)
    print('pdx203 stubs: ' + str(archive))


if __name__ == '__main__':
    main()
