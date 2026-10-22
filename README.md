<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg">
    <img alt="UniXNU" src="assets/logo-light.svg" width="200">
  </picture>
</p>

# UniXNU-pdx203

device repository for the sony xperia 1 ii (pdx203, sm8250 "kona", snapdragon 865, 8 GB ram, ufs 3.0). it holds the board file, the kernel defconfigs, the adt generator, the sm8250 variant of NativeUfs, the original ApplePMGR publication and the bring-up notes.

the port follows the sheng and uke device repositories. the hardware facts come from the [ios-sweet pdx203 port](https://github.com/chardidathing/ios-sweet/tree/pdx203), which booted its own xnu to the ios 16 lock screen on this phone, so the ram bank, the gic, the ufs host, the panel and the core numbering are verified on the device even though nothing from this repository has run on it yet.

- [documentation](https://unixnu.com)
- [porting guide](https://unixnu.com/porting/)
- [build](https://unixnu.com/building)
- [bring-up notes](docs/bring-up.md), the staged plan for this phone and what each stage prints

firmware: [uefi-pdx203](https://github.com/chardidathing/uefi-pdx203), the mu-silicium port (branch `pdx203`). its `[firmware]` block, preflight and boot image rule are in `board.toml`.

build with the `unixnu` driver of [UniXNU](https://github.com/UniXNU/UniXNU) (the fork [chardidathing/UniXNU](https://github.com/chardidathing/UniXNU) runs the macos workflow). clone with `--recurse-submodules`.

## state

| stage | state |
| --- | --- |
| 1 uefi firmware | built in uefi-pdx203, not booted |
| 2 unixnu menu | waits for 1 |
| 3 payload | the payload step runs on a mac, nothing booted yet |
| 4 darwinboot | nothing booted yet |
| 5 kernel entry | `pdx203_defconfig` builds and prelinks in ci ([run 39767686297](https://github.com/chardidathing/UniXNU-pdx203/actions/runs/39767686297)), not booted |
| 6 storage and root | `pdx203-full_defconfig` links NativeUfs on the sm8250 host and the pmgr publication, needs a first-console pass first, not booted |
| 7 userland | not started |

## layout

| path | contents |
| --- | --- |
| `board.toml` | board, ipsw, userdata geometry, prelink inputs, payload and adt options |
| `configs/pdx203_defconfig` | first-console kernel, platform expert, cpu driver, 4 KiB code signing, panic region |
| `configs/pdx203-full_defconfig` | stage 6 kernel, adds NativeUfs, NativeAES, mockfs, pthread and the pmgr publication, built after a first-console pass |
| `scripts/make-pdx203-adt.py` | the apple device tree of the phone |
| `scripts/check-host.py` | linux side checks: board file, defconfigs, scripts, the adt and its contract |
| `scripts/build-pdx203-archives.py` | the one archive builder board.toml lists, picks the builders from the selected flags |
| `scripts/build-pdx203-stubs.py`, `package/Pdx203Stubs.c` | weak `native_legacy_display_probe` for a kernel without the sheng display archive |
| `scripts/build-pdx203-platform-power.py`, `package/Pdx203PlatformPower.cpp` | the original ApplePMGR publication the unchanged amfi needs before a native ufs root |
| `scripts/build-arm-driver.py` | sheng's platform driver builder with the pdx203 include path |
| `scripts/check-pdx203.py` | the firmware preflight of uefi-pdx203, run by `unixnu build firmware` |
| `.github/workflows/macos-kernel.yml` | the kernel step of UniXNU's macos workflow, run from here |
| `drivers/NativeUfs` | sheng's NativeUfs on the kona gcc offsets, `qcom,sm8250-ufshc`, smmu stream from the adt |

## build

from the UniXNU checkout, the device repository next to it:

```sh
./unixnu defconfig pdx203_defconfig -D ../UniXNU-pdx203
./unixnu fetch
./unixnu ipsw fetch
./unixnu build kernel
./unixnu build package
./unixnu build firmware --uefi ../uefi-pdx203
./unixnu build payload --unique-chip-id <hex> --trust-cache <bundle> --data-ramdisk <seed>
python3 ../uefi-pdx203/scripts/pack-pdx203-bootimg.py --fd <SILICIUM_UEFI.fd> --ramdisk out/pdx203/payload/payload.img -o out/pdx203/boot/boot.img
```

the platform seed, the trust cache bundle and the data seed are device inputs, [docs/bring-up.md](docs/bring-up.md) says where sheng gets each one. the kernel step runs on macos, without a mac use the [macOS kernel workflow](https://github.com/chardidathing/UniXNU-pdx203/actions/workflows/macos-kernel.yml) of this repository (the kernel step of UniXNU's `macOS build`) with `defconfig=pdx203_defconfig` and `unixnu_ref=pdx203`, the fork branch with the one-line patch fix upstream main needs (docs/bring-up.md, stage 5).

host checks on linux:

```sh
python3 scripts/check-host.py
python3 ../UniXNU/unixnu status -D . --out out/driver
```

## what is verified and what is assumed

verified on the phone by ios-sweet: the ram bank `0x1_00000000 + 0xfcc00000`, gicv3 at `0x17a00000`/`0x17a60000`, the virtual timer on ppi 27 at 19.2 MHz, the eight cores with mpidr aff1 `0x000` to `0x700` and psci through smc, the ufshci 3.0 host at `0x1d84000` with userdata on lun 0 (4096-byte lbas, first lba `0x3cd75b`), the splash framebuffer at `0x9c000000` (1096x2560, stride 4384, a command mode panel), the boot image header the bootloader accepts and the absence of `fastboot boot`.

from the stock kona dtb and sony's kernel source, not yet seen by this code on the phone: the gcc ufs clock offsets, the reserved memory list, the gpu, gmu, gpucc and gpu smmu windows and stream ids, the mdss window, the ramoops range used as the panic log.

open inputs: the `[firmware]` block, the uefi memory map (which decides the darwinboot window and whether the panic log range stays reserved), the platform seed, the trust cache bundle and the data seed.

## device support

| feature | state | notes |
| --- | --- | --- |
| touch | ❌ | samsung sec_ts on geni se13, i2c 0x48, not ported |
| display | ❌ | command mode panel, the firmware kicks autorefresh, no xnu display provider yet |
| ufs | ⚠️ | NativeUfs builds for the sm8250 host, not run |
| wi-fi | ❌ | |
| bluetooth | ❌ | |
| camera | ❌ | |
| gpu | ❌ | adreno 650, the adt carries the node shape the port needs |
| usb | ❌ | dwc3 at `0xa600000`, high speed only works in ios-sweet |
| audio | ❌ | |
| sensors | ❌ | |
| battery driver | ❌ | |
| suspend and resume | ❌ | |

✅ available, ⚠️ partial, ❌ not available.

## license

BSD-2-Clause-Patent. see [LICENSE](LICENSE). `package/Pdx203PlatformPower.cpp` is sheng's `ShengPlatformPower.cpp` and keeps its MIT header.
