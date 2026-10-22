#!/usr/bin/env python3
"""decode the pdx203 adt and check the contract the drivers read, on any host.

ArmDTPlatform wants /cpus, /arm-io, /defaults, /options and a chrp nvram proxy in /chosen. ArmCpu wants
/arm-io/intc with an exact "arm,gic-v3" compatible, four u64 reg cells inside the arm-io window, a known
redistributor stride and /psci with a method. the darwinboot placeholders have to match the inputs.
"""
import contextlib
import importlib.util
import io
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pdx203_adt', ROOT / 'scripts/make-pdx203-adt.py')
adt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adt)


def decode(blob, offset=0, parent=''):
    nprops, nchildren = struct.unpack_from('<II', blob, offset)
    offset += 8
    props = {}
    for _ in range(nprops):
        name, size = struct.unpack_from('<32sI', blob, offset)
        offset += 36
        key = name.split(b'\0', 1)[0].decode()
        if key in props or offset + size > len(blob):
            raise ValueError('invalid property ' + key)
        props[key] = blob[offset:offset + size]
        offset += (size + 3) & ~3
    name = props['name'].rstrip(b'\0').decode()
    path = (parent.rstrip('/') + '/' + name) if parent else '/'
    result = {path: props}
    for _ in range(nchildren):
        children, offset = decode(blob, offset, path)
        result.update(children)
    return result, offset


class AdtTests(unittest.TestCase):
    def tree(self, *argv):
        args = adt.parse_args(['--output', 'unused', '--dram-size', '0xfcc00000', *argv])
        data = adt.build(args, seed=bytes(range(64)))
        nodes, offset = decode(data)
        self.assertEqual(offset, len(data))
        return nodes

    def board_args(self):
        return ['--cpu-regs', '0,0x100,0x200,0x300,0x400,0x500,0x600,0x700', '--psci-method', 'smc',
                '--owned-memory-size', '0x40000000', '--root-match-volume-uuid', '04769D26-2CA0-4825-B443-E2E5F88300F2',
                '--chip-id', '207', '--unique-chip-id', '1122334455667788', '--ipad-identity',
                '--packed-data-ramdisk', '--trust-cache']

    def test_platform_expert_nodes(self):
        tree = self.tree()
        for path in ['/chosen', '/chosen/memory-map', '/chosen/manifest-properties', '/cpus', '/cpus/cpu0',
                     '/defaults', '/options', '/product', '/arm-io', '/arm-io/intc', '/arm-io/ufshc', '/pram']:
            self.assertIn(path, tree)
        chosen = tree['/chosen']
        self.assertEqual(len(chosen['nvram-proxy-data']), 8192)
        self.assertEqual(struct.unpack('<I', chosen['nvram-bank-size'])[0], 8192)
        self.assertEqual(chosen['osenvironment'], b'main\0')
        self.assertEqual(struct.unpack('<Q', chosen['dram-base'])[0], 0x100000000)
        self.assertEqual(struct.unpack('<Q', chosen['dram-size'])[0], 0xfcc00000)
        self.assertEqual(tree['/arm-io']['device_type'], b'arm-io\0')
        self.assertNotIn('psci', [p.strip('/') for p in tree], 'one cpu adds no psci node')

    def test_gic_translates_to_the_kona_addresses(self):
        tree = self.tree(*self.board_args())
        bus = struct.unpack('<3Q', tree['/arm-io']['ranges'])
        self.assertNotEqual(bus[1], 0)
        intc = tree['/arm-io/intc']
        self.assertEqual(intc['compatible'], b'arm,gic-v3\0')
        regs = struct.unpack('<4Q', intc['reg'])
        self.assertEqual(bus[1] + regs[0] - bus[0], 0x17a00000)
        self.assertEqual(regs[1], 0x10000)
        self.assertEqual(bus[1] + regs[2] - bus[0], 0x17a60000)
        self.assertGreaterEqual(regs[3], 0x20000)
        self.assertLessEqual(regs[2] + regs[3], bus[2])
        self.assertEqual(struct.unpack('<Q', intc['redistributor-stride'])[0], 0x20000)
        self.assertEqual(tree['/psci']['method'], b'smc\0')

    def test_cpus_follow_the_mpidr_numbering(self):
        tree = self.tree(*self.board_args())
        for core in range(8):
            cpu = tree['/cpus/cpu%d' % core]
            self.assertEqual(struct.unpack('<I', cpu['reg'])[0], core << 8)
            self.assertEqual(cpu['device_type'], b'cpu\0')
            self.assertEqual(struct.unpack('<I', cpu['timebase-frequency'])[0], 19200000)
            self.assertEqual(cpu['state'], b'running\0' if core == 0 else b'waiting\0')
            self.assertEqual(cpu['compatible'], b'arm,cortex-a55\0' if core < 4 else b'arm,cortex-a77\0')

    def test_soc_windows(self):
        tree = self.tree(*self.board_args())
        bus = struct.unpack('<3Q', tree['/arm-io']['ranges'])
        phys = lambda path, index=0: bus[1] + struct.unpack('<Q', tree[path]['reg'][index * 16:index * 16 + 8])[0] - bus[0]
        self.assertEqual(phys('/arm-io/ufshc'), 0x1d84000)
        self.assertEqual(phys('/arm-io/ufshc', 1), 0x1d90000)
        self.assertEqual(phys('/arm-io/disp0'), 0xae00000)
        self.assertEqual(struct.unpack('<2Q', tree['/arm-io/disp0']['framebuffer']), (0x9c000000, 0x2300000))
        self.assertEqual(struct.unpack('<3I', tree['/arm-io/disp0']['width'] + tree['/arm-io/disp0']['height'] + tree['/arm-io/disp0']['stride']), (1096, 2560, 4384))
        self.assertEqual(phys('/arm-io/gpu'), 0x3d00000)
        self.assertEqual(phys('/arm-io/gmu'), 0x3d6a000)
        self.assertEqual(phys('/arm-io/gpucc'), 0x3d90000)
        self.assertEqual(phys('/arm-io/gpu-smmu'), 0x3da0000)
        self.assertEqual(phys('/arm-io/apps-smmu'), 0x15000000)
        self.assertEqual(struct.unpack('<I', tree['/arm-io/gpu']['chip-id'])[0], 0x06050000)
        self.assertIn(b'qcom,adreno\0', tree['/arm-io/gpu']['compatible'])
        self.assertEqual(tree['/arm-io/gmu']['compatible'], b'qcom,adreno-gmu\0')
        self.assertIn(b'qcom,adreno-smmu\0', tree['/arm-io/gpu-smmu']['compatible'])
        self.assertEqual(struct.unpack('<I', tree['/arm-io/gpu-smmu']['#iommu-cells'])[0], 2)
        self.assertEqual(struct.unpack('<4I', tree['/arm-io/gpu']['iommus'])[::2], (0x0, 0x2))
        self.assertEqual(struct.unpack('<4I', tree['/arm-io/gmu']['iommus'])[::2], (0x4, 0x5))
        self.assertNotIn('iommus', tree['/arm-io/ufshc'])
        self.assertIn(b'qcom,sm8250-ufshc\0', tree['/arm-io/ufshc']['compatible'])

    def test_darwinboot_placeholders_and_identity(self):
        tree = self.tree(*self.board_args())
        memory_map = tree['/chosen/memory-map']
        self.assertEqual(memory_map['PackedRAMDisk'], bytes(16))
        self.assertEqual(memory_map['TrustCache'], bytes(16))
        self.assertNotIn('RAMDisk', memory_map)
        self.assertNotIn('GpuAddon', memory_map)
        chosen = tree['/chosen']
        self.assertEqual(struct.unpack('<Q', chosen['darwinboot-memory-size'])[0], 0x40000000)
        self.assertEqual(struct.unpack('<I', chosen['chip-id'])[0], 0x207)
        self.assertEqual(struct.unpack('<Q', chosen['unique-chip-id'])[0], 0x1122334455667788)
        self.assertEqual(struct.unpack('<I', chosen['ephemeral-storage'])[0], 1)
        self.assertIn(b'04769D26-2CA0-4825-B443-E2E5F88300F2', chosen['root-matching'])
        self.assertEqual(struct.unpack('<I', chosen['amfi-only-platform-code'])[0], 1)
        self.assertEqual(tree['/']['model'], b'iPad7,1\0')
        self.assertEqual(tree['/']['target-type'], b'J120\0')
        self.assertEqual(tree['/']['compatible'], b'sony,pdx203\0qcom,sm8250\0')
        self.assertEqual(tree['/buttons']['home-button-type'], b'\x02\0\0\0')
        self.assertEqual(tree['/product']['model'], b'sony,pdx203\0')
        self.assertEqual(struct.unpack('<2Q', tree['/pram']['reg']), (0xffc00000, 0x100000))
        self.assertEqual(struct.unpack('<I', chosen['embedded-panic-log-size'])[0], 0x100000)

    def test_persistent_data_and_no_panic_log(self):
        tree = self.tree(*self.board_args(), '--persistent-data', '--no-panic-log')
        self.assertNotIn('ephemeral-storage', tree['/chosen'])
        self.assertNotIn('/pram', tree)
        self.assertNotIn('embedded-panic-log-size', tree['/chosen'])

    def test_refusals(self):
        for argv in (['--dram-size', '0x80000000'], ['--dram-size', '0xfcc00000', '--chip-id', '207'],
                     ['--dram-size', '0xfcc00000', '--owned-memory-size', '0x100000'],
                     ['--dram-size', '0xfcc00000', '--boot-manifest-hash', 'abc']):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                adt.parse_args(['--output', 'unused', *argv])
        with self.assertRaises(ValueError):
            adt.build(adt.parse_args(['--output', 'unused', '--dram-size', '0xfcc00000', '--cpu-regs', '0x100,0']))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], '-v'])
