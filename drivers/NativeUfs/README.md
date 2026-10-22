# NativeUfs (pdx203)

sm8250 variant of [UniXNU/NativeUfs](https://github.com/UniXNU/NativeUfs) at `af785c1777161a62931425c2faaa536ce0bebd5b` (the sheng driver), a device override of the same name. three things differ:

- `GccUfs.h` carries the kona ufs clock offsets from sony's `gcc-kona.c` and no ufs mem phy gdsc, the read-only probe skips that read
- the personality matches `qcom,sm8250-ufshc`
- the apps smmu stream comes from `/arm-io/ufshc` `iommus` and the stream plan is skipped when the node has none, which the pdx203 adt leaves out: the stock kona dtb gives the host no stream and the ios-sweet ufs driver did its dma above 4 GiB on this phone without touching the smmu

on top of that it carries uke's bring-up changes to the same driver (Allenwdk/UniXNU-uke, `drivers/NativeUfs`): the verified-block symbols stay behind their guard so the transport compiles without the policy bundle (`build-arm-driver.py NativeUfs --unverified`), `native-ufs-allow-unverified=1` publishes the OS/SystemOS windows unauthenticated and resolves the SystemOS volume by uuid for the owner mount, and the store waits for the root layout. a shipping build keeps the argument off and needs the verified path.

the host is ufshci 3.0 (`ver 0x300`, verified), the driver was written against sheng's. the `tests/` directory is the upstream one.
