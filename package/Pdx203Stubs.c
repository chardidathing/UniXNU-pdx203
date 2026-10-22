/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* weak fallback for the sheng legacy display probe, which the base bsd_init patch set calls behind the
 * offline-legacy-register boot argument whether or not the display archive is linked. the display
 * configuration links the strong definition and the linker drops this one. */
#include <pexpert/pexpert.h>

__attribute__((weak)) void
native_legacy_display_probe(void)
{
	kprintf("pdx203: native_legacy_display_probe: no display provider on this board yet\n");
}
