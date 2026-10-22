# NativeUfs (pdx203)

sm8250 variant of [UniXNU/NativeUfs](https://github.com/UniXNU/NativeUfs) at `af785c1777161a62931425c2faaa536ce0bebd5b` (the sheng driver), a device override of the same name. three things differ:

- `GccUfs.h` carries the kona ufs clock offsets from sony's `gcc-kona.c` and no ufs mem phy gdsc, the read-only probe skips that read
- the personality matches `qcom,sm8250-ufshc`
- the apps smmu stream comes from `/arm-io/ufshc` `iommus` and the stream plan is skipped when the node has none, which the pdx203 adt leaves out: the stock kona dtb gives the host no stream and the ios-sweet ufs driver did its dma above 4 GiB on this phone without touching the smmu

the host is ufshci 3.0 (`ver 0x300`, verified), the driver was written against sheng's. nothing else is changed. the `tests/` directory is the upstream one.
