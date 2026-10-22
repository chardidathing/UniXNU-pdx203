#!/usr/bin/env python3
"""host checks of the device repository, no mac, no phone: syntax, board file, adt generator and its contract."""
from pathlib import Path
import py_compile
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    board = tomllib.loads((ROOT / 'board.toml').read_text())
    for section in ('board', 'ipsw', 'userdata', 'kernel', 'firmware', 'payload'):
        if section not in board:
            raise SystemExit('board.toml: missing [%s]' % section)
    userdata = board['userdata']
    if userdata['last_lba'] <= userdata['first_lba'] or userdata['lba_bytes'] != 4096:
        raise SystemExit('board.toml: userdata geometry')
    capacity = (userdata['last_lba'] - userdata['first_lba'] + 1) * userdata['lba_bytes']
    print('userdata: %d MiB at lba %#x' % (capacity >> 20, userdata['first_lba']))
    for defconfig in sorted((ROOT / 'configs').glob('*_defconfig')):
        for number, line in enumerate(defconfig.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if not line.startswith('CONFIG_XNU_') or '=' not in line:
                raise SystemExit('%s:%d: not CONFIG_XNU_NAME=value' % (defconfig.name, number))
        print('defconfig: ' + defconfig.name)
    for script in sorted((ROOT / 'scripts').glob('*.py')):
        py_compile.compile(str(script), doraise=True)
    for entry in board['kernel']['archives']:
        name = entry.split()[0]
        if not (ROOT / 'scripts' / name).is_file() and not (ROOT.parent / 'UniXNU/scripts' / name).is_file():
            print('archive builder %s is not in this repository (expected from UniXNU/scripts)' % name)
    out = ROOT / 'out/pdx203.adt'
    out.parent.mkdir(exist_ok=True)
    adt = board['payload']['adt']
    command = [sys.executable, '-I', str(ROOT / adt['tool']), '--output', str(out), '--dram-size', board['payload']['dram_size']]
    for key, flag in (('owned_memory_size', '--owned-memory-size'), ('root_match_volume_uuid', '--root-match-volume-uuid'),
                      ('chip_id', '--chip-id'), ('cpu_regs', '--cpu-regs'), ('psci_method', '--psci-method')):
        if adt.get(key) is not None:
            command += [flag, str(adt[key])]
    if adt.get('chip_id') is not None:
        command += ['--unique-chip-id', '1']      # a stand-in seed, the real one never enters a repository
    if adt.get('ipad_identity'):
        command.append('--ipad-identity')
    if adt.get('packed_data_ramdisk'):
        command.append('--packed-data-ramdisk')
    command.append('--trust-cache')
    subprocess.run(command, check=True)
    subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/check-pdx203-adt.py')], check=True)
    print('PASS: board file, defconfigs, scripts and the adt contract')


if __name__ == '__main__':
    main()
