#!/usr/bin/env python3
"""run the archive builders the selected pdx203 configuration links, in sheng's order.

board.toml names this one script in [kernel] archives. the unixnu driver passes the defconfig's XNU_* flags
in the environment, so the same board file serves the first-console and the stage 6 configurations without
a builder list per defconfig. a builder that fails stops the kernel step, as a listed one would.
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def on(name):
    return os.environ.get('XNU_' + name, '0') == '1'


def main():
    steps = [
        ['build-corecrypto-14.py'],
        ['build-corecrypto-14.py', '--namespace'],
        ['build-arm-driver.py', 'ArmDTPlatform'],
        ['build-arm-driver.py', 'ArmCpu'],
    ]
    if not on('NATIVE_LEGACY_DISPLAY'):
        # the base bsd_init references native_legacy_display_probe() whatever the display flag says
        steps.append(['build-pdx203-stubs.py'])
    if on('NATIVE_AES'):
        steps += [['build-arm-driver.py', 'NativeAES'], ['build-native-aes-bindings.py']]
    if on('NATIVE_UFS'):
        steps += [['prepare-storage-headers.py'], ['build-arm-driver.py', 'NativeUfs']]
    if on('NATIVE_VIRTIO_BLOCK'):
        steps += [['build-arm-driver.py', 'NativeVirtioBlock'], ['build-native-virtio-bindings.py', '--component', 'NativeVirtioBlock']]
    if on('NATIVE_RAM_BLOCK'):
        steps += [['build-arm-driver.py', 'NativeRamBlock'],
                  ['build-native-virtio-bindings.py', '--component', 'NativeRamBlock', '--directory', 'build/native-ram-block']]
    if on('SOURCE_MOCKFS'):
        steps.append(['build-mockfs-fixture.py'])
    if on('SHENG_PMGR'):
        steps.append(['build-pdx203-platform-power.py'])
    if on('SOURCE_PTHREAD'):
        steps.append(['build-libpthread-kernel.py'])
    for index, step in enumerate(steps, 1):
        script = ROOT / 'scripts' / step[0]
        if not script.is_file():
            raise SystemExit('build-pdx203-archives: %s missing from the build tree' % script)
        print('pdx203 archive %d/%d: %s' % (index, len(steps), ' '.join(step)), flush=True)
        subprocess.run([sys.executable, str(script), *step[1:]], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
