// SPDX-License-Identifier: BSD-2-Clause-Patent
// sm8250 (kona) gcc registers used by ufs, transcribed from sony's msm-4.19 drivers/clk/qcom/gcc-kona.c
// (the ufs_phy branches, halt_reg = enable_reg on every one of them) and the stock dtb (qcom,gdsc@177004).
// the layout follows the sm8550 header of UniXNU/NativeUfs, only the offsets differ. no write is performed
// by NativeUfs here.
#ifndef NATIVE_UFS_GCC_UFS_H
#define NATIVE_UFS_GCC_UFS_H

// physical windows from the stock kona dtb (qcom,gcc@100000, ufshc@1d84000)
#define GCC_BASE                      0x00100000ULL
#define UFS_HC_BASE                   0x01d84000ULL
#define UFS_HC_SIZE                   0x3000ULL

#define GCC_UFS_PHY_GDSCR             0x77004
// kona has no separate ufs mem phy gdsc (sm8550: 0x9e000), 0 makes the read-only probe skip it
#define GCC_UFS_MEM_PHY_GDSCR         0

#define GCC_UFS_PHY_AXI_ENABLE        0x77010
#define GCC_UFS_PHY_AHB_ENABLE        0x77018
#define GCC_UFS_PHY_TX_SYMBOL0_ENABLE 0x7701c
#define GCC_UFS_PHY_RX_SYMBOL0_ENABLE 0x77020
#define GCC_UFS_PHY_UNIPRO_CORE_ENABLE 0x7705c
#define GCC_UFS_PHY_ICE_CORE_ENABLE   0x77064
#define GCC_UFS_PHY_PHY_AUX_ENABLE    0x7709c
#define GCC_UFS_PHY_RX_SYMBOL1_ENABLE 0x770b8
// bus_aggr_clk in the dtb: gcc_aggre_ufs_phy_axi_clk, halt/enable 0x770cc, hw clock gating bit 1
#define GCC_AGGRE_UFS_PHY_AXI_ENABLE  0x770cc

#define GCC_UFS_BRANCH_ENABLE_BIT     0x1U

// gcc_ufs_phy_axi_clk and gcc_aggre_ufs_phy_axi_clk have hwcg_bit 1 in gcc-kona.c, so CLK_OFF=1 on an
// idle branch is normal, as on sheng. the reset, rpmh and qmp phy programming are not represented, their
// semantics are not qualified on this phone and NativeUfs must not write them.
#endif
