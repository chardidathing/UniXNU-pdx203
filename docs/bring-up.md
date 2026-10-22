# bring-up of pdx203

the staged order of [unixnu.com/porting/bring-up](https://unixnu.com/porting/bring-up) applied to the sony xperia 1 ii. each stage says what it needs from this repository, what the phone shows when it works, and what is still an assumption. nothing from this repository has run on the phone yet, the verified column comes from the ios-sweet port (docs/PDX203.md and NOTES.md in that tree), which booted its own xnu to the ios 16 lock screen on this device.

## the phone

| item | value | verified |
| --- | --- | --- |
| soc | sm8250 "kona", 4x cortex-a55 (mpidr aff1 0x000 to 0x300) + 3x a77 (0x400 to 0x600) + 1x a77 prime (0x700), psci smc | yes, all eight run |
| ram | `0x80000000` + 2 GiB low bank with every kona carve-out, `0x1_00000000` + `0xfcc00000` upper bank (xnu's ram) | upper bank yes, low bank layout from the dtb |
| gic | gicv3, gicd `0x17a00000`/`0x10000`, gicr `0x17a60000`/`0x100000`, stride `0x20000` | yes |
| timer | 19.2 MHz counter, virtual timer ppi 27 | yes |
| ufs | ufshci 3.0 host at `0x1d84000`, ice `0x1d90000`, phy `0x1d87000`, lun 0 is the boot lun, 4096-byte lbas, disk last lba `0x3b947ff`, gpt 91 entries | yes |
| userdata | lun 0, lba `0x3cd75b` to `0x3b933fa`, 228444 MiB | first lba printed by the ios-sweet driver, last lba follows from its persistent log block |
| panel | 1096x2560 a8r8g8b8, stride 4384, splash buffer at `0x9c000000` (`cont_splash_region`, `0x2300000`), command mode with te, the mdp refreshes it once pingpong autorefresh is on (`shim/display.c` in ios-sweet) | yes |
| boot image | header v2, page 4096, base 0, kernel `0x8000`, ramdisk `0x2000000`, tags `0x1e00000`, dtb `0x1f00000`, the kona dtb set in the dtb field, flashed to `boot_a` | yes |
| bootloader | sony abl, no `fastboot boot` ("unknown command"), slot b blocked by lineage's vbmeta | yes |
| touch | samsung sec_ts, i2c 0x48 on geni se13 (`0xa94000`), irq tlmm 39, reset 38 | yes, later work |
| usb | dwc3 `0xa600000`, femto hs phy `0x88e3000`, usb0 behind the apps smmu stream 0 (identity context bank, s2cr bypass faults) | yes, later work |
| gpu | adreno 650, kgsl `0x3d00000`, gmu `0x3d6a000`, gpucc `0x3d90000`, gpu smmu `0x3da0000`, chip id `0x06050000`, sids user 0, secure 2, gmu 4 and 5 | dtb only |
| panic log | ramoops carve-out `0xffc00000`/`0x100000`, no-map in the stock dtb | dtb only |
| ufs clocks | gcc at `0x100000`, ufs_phy branches `0x77010` axi, `0x77018` ahb, `0x7701c` tx, `0x77020` rx0, `0x7705c` unipro, `0x77064` ice, `0x7709c` aux, `0x770b8` rx1, `0x770cc` aggre axi, gdsc `0x77004` | gcc-kona.c only |

the stock dtb gives the ufs host no apps smmu stream (mainline sm8250 says 0xe0) and the ios-sweet driver did dma above 4 GiB without touching the smmu. the pdx203 adt therefore emits no `iommus` on `/arm-io/ufshc` and drivers/NativeUfs skips the stream plan. if NativeUfs faults on its first dma, add `('iommus', u32(0xe0, 0))` to the ufshc node and the driver programs the bypass context bank the way it does on sheng.

## stage 1, uefi

owned by [uefi-pdx203](https://github.com/chardidathing/uefi-pdx203) (branch `pdx203`, its `docs/pdx203.md` has the port notes). what came over from it is in `board.toml`: the `[firmware]` block, `scripts/check-pdx203.py` (the preflight, wants `UNIXNU_UEFI=<uefi checkout>`) and the boot image rule. the fd loads at `0x9fc00000`, 3 MiB, as on the other kona boards of mu-silicium.

the bootloader has only been seen to boot the stock header v2 layout with the dtb in its own section, which `unixnu bootimg` cannot write (it appends the dtb to the gzip stream), so the flashable image is packed by the uefi checkout:

```sh
python3 ../uefi-pdx203/scripts/pack-pdx203-bootimg.py --fd ../uefi-pdx203/Build/pdx203Pkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
    --ramdisk out/pdx203/payload/payload.img -o out/pdx203/boot/boot.img
fastboot flash boot_a out/pdx203/boot/boot.img       # no fastboot boot on this bootloader, keep a copy of the stock boot_a
```

still to confirm against that port: that its memory map keeps `0xffc00000`/`0x100000` reserved (the panic log the kernel maps write-combined, pass `--no-panic-log` to the adt tool otherwise) and leaves a conventional run of at least `owned_memory_size` (1 GiB in `board.toml`, 256 MiB is enough for stage 5) for darwinboot, and that the autorefresh and tearcheck kick for the command mode panel is in, otherwise the gop framebuffer is never scanned out and every later stage is dark.

expected: the mu-silicium menu on the panel. no uart on this phone, every log is the panel.

## stage 2, unixnu menu

expected: `UNIXNU:` lines on the panel, the entry count, the kit count, the `pdx203 first boot: source 4K XNU to console` entry. the payload volume label is `PDX203ESP`.

## stage 3, payload

built on a mac or in the macos workflow with `steps=kernel userdata payload`. inputs:

| input | where sheng gets it | pdx203 |
| --- | --- | --- |
| platform seed `--unique-chip-id` | a hex value kept outside every repository, the repository secret `UNIXNU_UNIQUE_CHIP_ID` in the workflow | same, any nonzero 64-bit value, it seeds IOPlatformUUID and nothing else |
| trust cache bundle `--trust-cache` | the original `StaticTrustCache` and `Cryptex1,SystemTrustCache` of the ipsw packed with `scripts/make-owner-trust-bundle.py` in UniXNU, the two accepted hashes are in `board.toml` | same ipsw, same bundle, same hashes |
| data seed `--data-ramdisk` | a packed apfs data volume (`DBRDISK1`) made with `scripts/prepare-offline-data.py` in UniXNU, grown with `seed-data-grow.py`, setup skipped with `--skip-setup` | same, the volume uuid goes into `CONFIG_XNU_OWNER_DATA_VOLUME_UUID` of the stage 7 kernel |

the kernel step alone needs none of them. the adt is `scripts/make-pdx203-adt.py`, checked on linux by `scripts/check-host.py`.

## stage 4, darwinboot

expected on the panel: `DARWINBOOT: loader v2 installed EL1`, the virtual and physical base, the window, `video base 0x9c000000` 1096x2560, `inputs validated; exiting boot services`.

a refusal is `boot refused: <status>; firmware retained` and the menu comes back. the usual causes are a window larger than the biggest conventional run (lower `owned_memory_size`) or a placeholder missing for an input the payload carried (the adt makes one for every input the stock payload step passes).

## stage 5, kernel entry

the first-console kernel, `configs/pdx203_defconfig`:

```sh
./unixnu defconfig pdx203_defconfig -D ../UniXNU-pdx203
./unixnu build kernel
```

in ci, the `macOS kernel` workflow of this repository (`.github/workflows/macos-kernel.yml`, the kernel step of UniXNU's `macOS build` with the same tools and artifact layout): `defconfig=pdx203_defconfig`, `unixnu_repository=chardidathing/UniXNU`, `unixnu_ref=pdx203`, no `pre_build`. green run: https://github.com/chardidathing/UniXNU-pdx203/actions/runs/39767686297, `kernel.macho` sha256 `7e77d7350a395599317cdc2e018ce03055c995385729b7c462242e01dc02895d`, 51802112 bytes, 30 prelinked components. two things about that:

- `unixnu_ref` is the fork's `pdx203` branch, not `main`: upstream UniXNU since `c4af0f0` (the gpu addon mount) sets `BINDM_FORCE_ROOT` in `bind_vfsops.c` without defining it, so a clean tree stops at `bind_vfsops.o`. the branch carries the one-hunk fix in `patches/xnu/zzy-native-gpu-addon-mount.patch` (it belongs upstream)
- the fork's own `macOS build` workflow (`UniXNU/.github/workflows/macos.yml`) is not registered yet: github lists a fork's workflows only after a push to its default branch, which this port has not done. the `pdx203` branch already carries the comment commit that registers it, `git push origin pdx203:main` on the fork is all it takes, then `gh workflow run macos.yml -R chardidathing/UniXNU -f device_repository=chardidathing/UniXNU-pdx203 -f defconfig=pdx203_defconfig -f steps=kernel` works as documented upstream. the github contents listings `prepare-xnu-source.py` reads are rate limited on the shared runners, the device workflow fetches them with the job token first

locally the driver runs the bootstrap pass for the compile records (its link fails on the display probe reference, which is expected and tolerated), then `scripts/build-pdx203-archives.py` builds corecrypto, ArmDTPlatform, ArmCpu and the display stub, then the real pass links and prelinks against the pinned 21H461 kernelcache.

expected on the panel: the darwinboot green bar, then the xnu banner and the verbose log (`-v`, `-enable_kprintf_spam`), `ArmDTPlatform` publishing the arm-io children, `ArmCpu` registering cpu 0 and taking timer interrupts (`armcpu-diagnostics=1` prints the counts), then the wait for a root device. a panic names the missing provider and stays on the panel (`panic_screen = true`).

what to expect to go wrong first:

- nothing after the green bar: the video console. darwinboot hands over the gop base without the low "physical" bit and the stock `initialize_screen` may not map it. uke carries two patches for this (`zzzzz-video-console-physical-fb.patch`, `zzzzzz-video-console-text.patch` in UniXNU-uke) and a `-uketextconsole` argument. a device `patches/xnu` directory replaces the whole base set, so the way to carry them is a `pdx203` branch of the UniXNU fork, not this repository
- a panic in ArmCpu about the gic: the arm-io window is the whole soc from `0x01000000`, the gic reg cells are offsets inside it, check `scripts/check-host.py` still passes and the gicr region is at least `0x20000`
- the kernel resets instead of printing: the darwinboot window in the low bank over a carve-out, or `serial=3` poking the bcm2837 uart address. both sheng and uke boot with `serial=3`, so try the window first

secondary cores: `cpu_regs` lists all eight, ArmCpu starts them only with `sheng-smp=1` (`--kernel-arg sheng-smp=1`). ios-sweet ran all eight through psci on this phone, so after cpu 0 is stable that is the next argument.

## stage 6, storage and root

the stage 6 kernel, `configs/pdx203-full_defconfig`, adds NativeUfs (drivers/NativeUfs, the sm8250 variant), NativeAES with the recorded original bindings, mockfs, source pthread and the original ApplePMGR publication. two of its builders read a prelinked candidate of the pinned kernelcache, so a first-console build has to run first and leave its kernel where they look, the way the uke workflow does it with its bootstrap pass (a kernel with no archive at all does not link on the stock tree, the display probe reference again, so the first-console configuration is the candidate producer here). in the device workflow that is the `pre_build` input:

```sh
./unixnu defconfig pdx203_defconfig -D "$DEVICE_DIR"
./unixnu build kernel -D "$DEVICE_DIR"
mkdir -p out/pdx203/tree/build/native-prelink
for name in native-defaults native-owner-ufs-cpu-desktop-v9-hid-init; do
  cp out/pdx203/kernel/kernel.macho out/pdx203/tree/build/native-prelink/$name-candidate.macho
  cp out/pdx203/kernel/kernel.json out/pdx203/tree/build/native-prelink/$name-candidate.json
done
rm -f out/pdx203/kernel/kernel.macho out/pdx203/kernel/kernel.json
mkdir -p out/pdx203/tree/.cache/firmware/kernelcache.macho
cp "$(find out -name kernelcache.decompressed -print -quit)" out/pdx203/tree/.cache/firmware/kernelcache.macho/kernelcache.release.ipad7.decompressed
```

then `defconfig=pdx203-full_defconfig` with `unixnu_ref=pdx203`. the payload for it adds `--kernel-arg native-ufs-root=1 --kernel-arg sheng-pmgr=2`, the payload step refuses `native-ufs-root=1` on a kernel without the linked pmgr publication.

why the pmgr: `CONFIG_XNU_SHENG_PMGR` links `package/Pdx203PlatformPower.cpp` and the base patch `sheng-platform-power.patch` calls `sheng_pmgr_run()` from `bsd_init`. with `sheng-pmgr=2` it loads the kernelcache's own `com.apple.driver.ApplePMGR`, instantiates the original class with an empty description and publishes an `ApplePMGRNub`, because the unchanged AppleMobileFileIntegrity panics `No PMGR` when it starts without one. nothing in it is sheng hardware, it binds to addresses of the pinned kernelcache, so the pdx203 copy is the sheng source with the file renamed. the names `sheng_pmgr_run` and `sheng-pmgr` are the vocabulary of the base patch and the payload check and stay.

expected on the panel: `NativeUfs` adopting the running controller (`native-ufs-probe=3` first, read-only, prints the version register `0x300`, the capabilities and a `READ CAPACITY`), then with `native-ufs-root=1` the root layout from the `SHNGROOT` manifest, the `OS` and `SystemOS` windows, the apfs volumes, the root match on `04769D26-2CA0-4825-B443-E2E5F88300F2` and `launchd`.

the userdata image: `steps=kernel userdata` in the workflow, `fastboot flash userdata out/pdx203/userdata/userdata-root.img` from the bootloader (this erases android's data, lun 0 geometry from `board.toml`).

open on this stage:

- the apps smmu stream of the ufs host, see the top of this file
- the kona gcc offsets in `drivers/NativeUfs/GccUfs.h` are transcribed, `native-ufs-probe=2` prints the branch registers read-only before anything is adopted
- the owner-root path (`VERIFIED_ROOT_PROBE`, `OWNER_ROOT_*`) needs the signed policy bundle made from the real OS/SystemOS images on a mac, as on sheng. the uke port mounts the system volume unverified with its `native-ufs-allow-unverified` patch instead, which is a fork change, not a device repository one

## stage 7, userland

not started. it needs the display provider (the sheng legacy display archive, built from the uke-style `pre_build` with the mobile graphics candidate, plus a presenter for the command mode mdp), the data seed with its volume uuid in the defconfig, the owner-root mounts, and touch (geni i2c + sec_ts in the NativeGeniSpi style). the ipad identity in the adt is already the one sheng runs with.

## gpu, for the adreno 650 port

the adt publishes the nodes NativeAdreno reads, with the kona values: `/arm-io/gpu` (`qcom,adreno-650.0`, `qcom,adreno`, reg kgsl, cx_dbgc, rscc, `chip-id` `0x06050000`, `iommus` sids 0 and 2), `/arm-io/gmu` (`qcom,adreno-gmu`, reg gmu, pdc cfg, pdc seq, `iommus` sids 4 and 5), `/arm-io/gpucc` (`qcom,gpucc-kona`) and `/arm-io/gpu-smmu` (`qcom,adreno-smmu`, `#iommu-cells` 2). the driver itself knows the 740 and sheng's board probe powers the gpu from constants, so the 650 port starts in the driver and in a `package/` probe, not in the tree.

## what each check prints on linux

```sh
python3 scripts/check-host.py          # board file, defconfigs, py_compile, the adt and 7 contract tests
python3 ../UniXNU/unixnu status -D . --out out/driver   # NativeUfs and the package from "device", the rest "base"
python3 ../UniXNU/unixnu tree -D . --out out/driver     # the build tree with kits/pdx203 and the merged scripts
```
