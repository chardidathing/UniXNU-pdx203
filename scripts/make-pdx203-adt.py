#!/usr/bin/env python3
"""apple-format device tree of the sony xperia 1 ii (pdx203, sm8250) for darwinboot and the source xnu.

the node set is what ArmDTPlatform, ArmCpu, NativeUfs and NativeAdreno read (the same shape as the sheng
and uke trees), the addresses are the stock kona dtb's, and the values ios-sweet verified on the phone are
taken from its board table (tools/boards/pdx203.py): the upper ddr bank, the gic, the 19.2 MHz counter,
the ufs host, the splash framebuffer and the mpidr numbering. everything else is marked in docs/bring-up.md.
"""
from pathlib import Path
import argparse
import os
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]

# ram xnu manages: the upper ddr bank. the low bank (0x80000000, 2 GiB) holds every kona carve-out and the
# splash framebuffer, darwinboot's window comes from the uefi memory map either way.
DRAM_BASE = 0x100000000
DRAM_SIZE = 0xfcc00000

# one arm-io window over the whole soc so the gic, ufs, mdss, gpu and smmu can all be children with
# reg = phys - ARMIO_BASE (sheng's 0x17000000 apss window can't express the gpu at 0x3d00000).
# not 0: pexpert takes the soc base from this and bails on zero.
ARMIO_BASE = 0x01000000
ARMIO_SIZE = 0x100000000 - ARMIO_BASE

GICD, GICD_SIZE = 0x17a00000, 0x10000
GICR, GICR_SIZE = 0x17a60000, 0x100000
GICR_STRIDE = 0x20000              # kona: redistributor-stride <0 0x20000>, 8 frames in 0x100000
TIMEBASE = 19200000                # the virtual timer is ppi 27, what ArmCpu enables
UFS_HC, UFS_HC_SIZE = 0x1d84000, 0x3000
UFS_ICE, UFS_ICE_SIZE = 0x1d90000, 0x8000
UFS_PHY, UFS_PHY_SIZE = 0x1d87000, 0x1000
# splash framebuffer abl leaves at cont_splash_region, 1096x2560 a8r8g8b8 stride 4384 (verified), the
# command mode panel refreshes it once the uefi port kicks pingpong autorefresh
FB_BASE, FB_SIZE = 0x9c000000, 0x2300000
FB_WIDTH, FB_HEIGHT, FB_STRIDE = 1096, 2560, 4384
MDSS, MDSS_SIZE = 0xae00000, 0x84208
# adreno 650: kgsl, gmu with its pdc windows, gpucc, the gpu smmu and the four stream ids of the stock dtb
GPU, GPU_SIZE = 0x3d00000, 0x40000
GPU_CX_DBGC, GPU_CX_DBGC_SIZE = 0x3d61000, 0x800
GPU_RSCC, GPU_RSCC_SIZE = 0x3de0000, 0x10000
GPU_CHIP_ID = 0x06050000
GMU, GMU_SIZE = 0x3d6a000, 0x30000
GMU_PDC_CFG, GMU_PDC_CFG_SIZE = 0xb290000, 0x10000
GMU_PDC_SEQ, GMU_PDC_SEQ_SIZE = 0xb490000, 0x10000
GPUCC, GPUCC_SIZE = 0x3d90000, 0x9000
GPU_SMMU, GPU_SMMU_SIZE = 0x3da0000, 0x10000
GPU_SID_USER, GPU_SID_SECURE, GMU_SID_USER, GMU_SID_KERNEL = 0x0, 0x2, 0x4, 0x5
APPS_SMMU, APPS_SMMU_SIZE = 0x15000000, 0x100000
# xnu's embedded panic log: the kona ramoops carve-out, no-map in the stock dtb so nothing else owns it.
# the uefi memory map must keep it reserved too (docs/bring-up.md), the kernel maps it write-combined.
PANIC_LOG_BASE, PANIC_LOG_SIZE = 0xffc00000, 0x100000

CPU_COMPATIBLE = ['arm,cortex-a55'] * 4 + ['arm,cortex-a77'] * 4


def u32(*values):
    return struct.pack('<%dI' % len(values), *values)


def u64(*values):
    return struct.pack('<%dQ' % len(values), *values)


def cstr(*values):
    return b''.join(value.encode() + b'\0' for value in values)


def node(name, properties=(), children=()):
    properties = [('name', cstr(name)), *properties]
    result = struct.pack('<II', len(properties), len(children))
    for key, data in properties:
        encoded = key.encode()
        if len(encoded) > 31:
            raise ValueError('adt property name over 31 bytes: ' + key)
        result += struct.pack('<32sI', encoded, len(data))
        result += data + bytes(-len(data) % 4)
    return result + b''.join(children)


def empty_nvram_proxy():
    """a fresh volatile chrp bank for the real IODTNVRAM, there is no nvram controller on this path."""
    def header(name, size):
        raw = bytearray(struct.pack('<BBH12s', 0x70, 0, size // 16, name))
        checksum = sum(raw)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        raw[1] = checksum
        return raw

    image = bytearray(8192)
    image[:16] = header(b'nvram', 32)
    image[32:48] = header(b'common', 16 + 2048)
    free_at = 32 + 16 + 2048
    image[free_at:free_at + 16] = header(b'free', len(image) - free_at)
    struct.pack_into('<I', image, 16, zlib.adler32(image[20:]))
    return [('nvram-bank-size', u32(len(image))), ('nvram-bank-count', u32(1)),
            ('nvram-current-bank', u32(0)), ('nvram-proxy-data', bytes(image))]


def io(phys):
    """arm-io child address of a soc register window."""
    if phys < ARMIO_BASE or phys >= ARMIO_BASE + ARMIO_SIZE:
        raise ValueError('outside the arm-io window: %#x' % phys)
    return phys - ARMIO_BASE


def build(args, seed=None):
    seed = os.urandom(64) if seed is None else seed
    if len(seed) != 64:
        raise ValueError('random seed must be 64 bytes')
    cpu_regs = [int(value, 0) for value in args.cpu_regs.split(',')]
    if (not cpu_regs or cpu_regs[0] != 0 or len(set(cpu_regs)) != len(cpu_regs) or len(cpu_regs) > 8
            or any(reg < 0 or reg > 0xffff or reg & 0xff for reg in cpu_regs)):
        raise ValueError('--cpu-regs: up to eight distinct aff1-numbered cores, boot cpu 0 first')
    cpus = [node('cpu%d' % index, [('state', cstr('running' if index == 0 else 'waiting')),
                                   ('reg', u32(reg)),
                                   ('device_type', cstr('cpu')),
                                   ('compatible', cstr(CPU_COMPATIBLE[reg >> 8])),
                                   ('timebase-frequency', u32(TIMEBASE))])
            for index, reg in enumerate(cpu_regs)]
    data_disk = args.data_ramdisk or args.packed_data_ramdisk
    chosen = [
        ('random-seed', seed),
        # without these xnu never publishes IOPlatformUUID and gethostuuid() blocks forever for callers
        # (configd) that pass a zero timeout
        *([('unique-chip-id', u64(args.unique_chip_id)), ('chip-id', u32(args.chip_id))]
          if args.unique_chip_id is not None else []),
        ('osenvironment', cstr('main')),
        # security status of a dev-fused, undemoted board (0,0,1,1): mobileactivationd then takes its native
        # activation branch without an activation record. established on hardware by ios-sweet.
        *([('certificate-production-status', u32(0)), ('effective-production-status-ap', u32(0)),
           ('certificate-security-mode', u32(1)), ('effective-security-mode-sep', u32(1))]
          if args.ipad_identity else []),
        # a volatile data disk is ephemeral storage, a persistent one (sheng-data-persist) is not, otherwise
        # datamigrator skips every migration and the staged system apps never install
        *([('ephemeral-storage', u32(1))] if data_disk and not args.persistent_data else []),
        *([('darwinboot-memory-size', u64(args.owned_memory_size))] if args.owned_memory_size else []),
        ('dram-base', u64(DRAM_BASE)),
        ('dram-size', u64(args.dram_size)),
        *([('embedded-panic-log-size', u32(PANIC_LOG_SIZE))] if args.panic_log else []),
        # image4 hash algorithm, as the target ipad's tree says. selects the algorithm only.
        ('crypto-hash-method', cstr('sha2-384')),
        # mount(8) phase 1 names /private/preboot/<hash> after this. no apple manifest exists here, the
        # stock driver does not pass one yet, so it is an explicit owner identity when it is given at all.
        *([('boot-manifest-hash', bytes.fromhex(args.boot_manifest_hash))] if args.boot_manifest_hash else []),
        *([('root-matching', cstr('<dict><key>IOProviderClass</key><string>IOMedia</string>'
                                  '<key>IOPropertyMatch</key><dict><key>UUID</key><string>' +
                                  args.root_match_volume_uuid.upper() + '</string></dict></dict>'))]
          if args.root_match_volume_uuid else []),
        # strict policy for the original amfi: platform code only. keeps it enforcing.
        ('amfi-only-platform-code', u32(1)),
        *([('text-fixups', cstr(*args.text_fixup))] if args.text_fixup else []),
        *empty_nvram_proxy(),
    ]
    memory_map = ([('PackedRAMDisk' if args.packed_data_ramdisk else 'RAMDisk', bytes(16))] if data_disk else []) + \
                 ([('TrustCache', bytes(16))] if args.trust_cache else []) + \
                 ([('GpuAddon', bytes(16))] if args.gpu_addon else [])
    arm_io_children = [
        node('intc', [('compatible', cstr('arm,gic-v3')),
                      ('reg', u64(io(GICD), GICD_SIZE, io(GICR), GICR_SIZE)),
                      ('redistributor-stride', u64(GICR_STRIDE))]),
        # ufs host, ice and phy windows. the stock kona dtb gives the host no apps smmu stream (mainline
        # sm8250 says 0xe0) and ios-sweet's driver did dma above 4 GiB without touching the smmu, so no
        # iommus here: drivers/NativeUfs skips the stream plan when the property is absent.
        node('ufshc', [('compatible', cstr('qcom,sm8250-ufshc', 'qcom,ufshc')),
                       ('reg', u64(io(UFS_HC), UFS_HC_SIZE, io(UFS_ICE), UFS_ICE_SIZE, io(UFS_PHY), UFS_PHY_SIZE))]),
        # the display processor and the splash buffer. IOMobileFramebuffer counts arm-io children with this
        # device_type, the display driver (not written) reads the panel geometry from here.
        node('disp0', [('device_type', cstr('display-subsystem')),
                       ('compatible', cstr('sony,pdx203-display', 'qcom,sde-kms')),
                       ('reg', u64(io(MDSS), MDSS_SIZE)),
                       ('framebuffer', u64(FB_BASE, FB_SIZE)),
                       ('width', u32(FB_WIDTH)), ('height', u32(FB_HEIGHT)), ('stride', u32(FB_STRIDE)),
                       ('panel-mode', cstr('command'))]),
        # adreno 650 nodes in the shape NativeAdreno reads (compatible needles qcom,adreno, qcom,adreno-gmu,
        # qcom,adreno-smmu, reg parsed with the node's own cells, stream ids from iommus against the smmu's
        # #iommu-cells). the driver knows the 740 only, these are the inputs the 650 port needs.
        node('gpu', [('compatible', cstr('qcom,adreno-650.0', 'qcom,adreno')),
                     ('#address-cells', u32(2)), ('#size-cells', u32(2)),
                     ('reg', u64(io(GPU), GPU_SIZE, io(GPU_CX_DBGC), GPU_CX_DBGC_SIZE, io(GPU_RSCC), GPU_RSCC_SIZE)),
                     ('chip-id', u32(GPU_CHIP_ID)),
                     ('iommus', u32(GPU_SID_USER, 0x401, GPU_SID_SECURE, 0x400))]),
        node('gmu', [('compatible', cstr('qcom,adreno-gmu')),
                     ('#address-cells', u32(2)), ('#size-cells', u32(2)),
                     ('reg', u64(io(GMU), GMU_SIZE, io(GMU_PDC_CFG), GMU_PDC_CFG_SIZE, io(GMU_PDC_SEQ), GMU_PDC_SEQ_SIZE)),
                     ('iommus', u32(GMU_SID_USER, 0x400, GMU_SID_KERNEL, 0x400))]),
        node('gpucc', [('compatible', cstr('qcom,gpucc-kona')),
                       ('#address-cells', u32(2)), ('#size-cells', u32(2)),
                       ('reg', u64(io(GPUCC), GPUCC_SIZE))]),
        node('gpu-smmu', [('compatible', cstr('qcom,adreno-smmu', 'qcom,kgsl-smmu-v2')),
                          ('#address-cells', u32(2)), ('#size-cells', u32(2)),
                          ('#iommu-cells', u32(2)),
                          ('reg', u64(io(GPU_SMMU), GPU_SMMU_SIZE))]),
        node('apps-smmu', [('compatible', cstr('qcom,qsmmu-v500')),
                           ('#address-cells', u32(2)), ('#size-cells', u32(2)),
                           ('#iommu-cells', u32(2)),
                           ('reg', u64(io(APPS_SMMU), APPS_SMMU_SIZE))]),
    ]
    tree = node('device-tree', [
        # hw.product/hw.machine come from the root model and target-type, libMobileGestalt prefix-matches
        # hw.product against iPad, so the ipad identity needs both here
        ('model', cstr('iPad7,1') if args.ipad_identity else cstr('pdx203-first-boot')),
        *([('target-type', cstr('J120'))] if args.ipad_identity else []),
        ('compatible', cstr('sony,pdx203', 'qcom,sm8250')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [
        node('chosen', chosen, [node('memory-map', memory_map),
                                # read by the original AppleImage4 at start, present and empty
                                node('manifest-properties')]),
        node('cpus', children=cpus),
        *([node('psci', [('compatible', cstr('arm,psci-1.0')), ('method', cstr(args.psci_method))])] if len(cpus) > 1 else []),
        # no suspend on this board, so the cpu never parks. kern.maxvnodes is sheng's formula for the 4 GiB
        # ipad (memory/64K + 1024), the xsmall vnode limit otherwise makes vnode jetsam kill idle daemons.
        node('defaults', [('sleep-disabled', u32(1)), ('kern.maxvnodes', u32(66560))]),
        node('options', []),
        *([node('pram', [('reg', u64(PANIC_LOG_BASE, PANIC_LOG_SIZE))])] if args.panic_log else []),
        # no home button, 2 is the non-mechanical answer BSPlatform passes through
        *([node('buttons', [('compatible', cstr('buttons')), ('device_type', cstr('buttons')),
                            ('button-names', cstr('hold', 'voldown', 'volup')),
                            ('home-button-type', u32(2))])] if args.ipad_identity else []),
        # the original AppleImage4 panics without a product node
        node('product', [('product-name', cstr('iPad Pro (12.9-inch) (2nd generation)') if args.ipad_identity else cstr('Xperia 1 II')),
                         ('model', cstr('sony,pdx203')),
                         *([('product-description', cstr('iPad Pro (12.9-inch) (2nd generation)')),
                            ('artwork-device-idiom', cstr('pad')),
                            ('artwork-device-subtype', u32(2732)),
                            ('artwork-scale-factor', u32(2)),
                            ('artwork-display-gamut', cstr('P3')),
                            ('compatible-device-fallback', cstr('iPad6,7')),
                            ('thin-bezel', u32(1))] if args.ipad_identity else [])]),
        node('arm-io', [('device_type', cstr('arm-io')),
                        ('#address-cells', u32(2)),
                        ('#size-cells', u32(2)),
                        ('ranges', u64(0, ARMIO_BASE, ARMIO_SIZE))], arm_io_children),
    ])
    return tree


def parse_args(argv=None):
    hexint = lambda value: int(value, 16)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/pdx203/boot/kernel.macho.adt')
    parser.add_argument('--dram-size', type=lambda value: int(value, 0), required=True,
                        help='size of the upper ddr bank xnu manages, 0xfcc00000 on this phone')
    parser.add_argument('--owned-memory-size', type=lambda value: int(value, 0), default=None,
                        help='darwinboot contiguous window request, 256 MiB to 8 GiB in 2 MiB steps')
    parser.add_argument('--root-match-volume-uuid', default=None,
                        help='/chosen/root-matching: the IOMedia uuid of the root volume')
    parser.add_argument('--unique-chip-id', type=hexint, default=None,
                        help='/chosen/unique-chip-id (8 bytes), with --chip-id seeds IOPlatformUUID. software identity, not a soc id')
    parser.add_argument('--chip-id', type=hexint, default=None)
    parser.add_argument('--ipad-identity', action='store_true',
                        help='root, /product and /buttons describe the iPad7,1 whose userland runs here')
    parser.add_argument('--cpu-regs', default='0',
                        help='comma separated mpidr aff1 values of the cores, boot cpu 0 first. more than one adds /psci')
    parser.add_argument('--psci-method', choices=['smc', 'hvc'], default='smc')
    parser.add_argument('--packed-data-ramdisk', action='store_true', help='PackedRAMDisk placeholder for a DBRDISK1 data seed')
    parser.add_argument('--data-ramdisk', action='store_true', help='RAMDisk placeholder for a dense data seed')
    parser.add_argument('--persistent-data', action='store_true', help='the data disk keeps its writes, so no ephemeral-storage')
    parser.add_argument('--trust-cache', action='store_true', help='TrustCache placeholder')
    parser.add_argument('--gpu-addon', action='store_true', help='GpuAddon placeholder')
    parser.add_argument('--text-fixup', action='append', default=[], help='/chosen/text-fixups entry')
    parser.add_argument('--boot-manifest-hash', default=None, help='sha-384 hex of the owner boot set, optional')
    parser.add_argument('--no-panic-log', dest='panic_log', action='store_false',
                        help='leave out /pram and embedded-panic-log-size (when the uefi map does not reserve the ramoops range)')
    args = parser.parse_args(argv)
    if (args.unique_chip_id is None) != (args.chip_id is None):
        parser.error('--unique-chip-id and --chip-id go together')
    if args.unique_chip_id is not None and not (0 < args.unique_chip_id < 1 << 64 and 0 < args.chip_id < 1 << 32):
        parser.error('--unique-chip-id fits 8 bytes and --chip-id 4 bytes, both nonzero')
    if args.owned_memory_size is not None and (
            not 0x10000000 <= args.owned_memory_size <= 0x200000000 or args.owned_memory_size % 0x200000):
        parser.error('owned memory is 256 MiB to 8 GiB, aligned to 2 MiB')
    if args.dram_size != DRAM_SIZE:
        parser.error('--dram-size is the upper bank, 0xfcc00000, until a live fdt says otherwise')
    if args.boot_manifest_hash is not None and (len(args.boot_manifest_hash) != 96 or
                                                any(c not in '0123456789abcdefABCDEF' for c in args.boot_manifest_hash)):
        parser.error('--boot-manifest-hash is 48 bytes of hex')
    return args


def main():
    args = parse_args()
    try:
        tree = build(args)
    except ValueError as error:
        raise SystemExit('make-pdx203-adt: ' + str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(tree)
    print('pdx203 adt: %d bytes, dram %#x, %d cpus, timebase %d' % (len(tree), args.dram_size, args.cpu_regs.count(',') + 1, TIMEBASE))


if __name__ == '__main__':
    main()
