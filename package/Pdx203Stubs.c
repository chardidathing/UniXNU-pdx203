/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* weak fallbacks for symbols the base tree references whether or not their archive is linked: the sheng
 * legacy display probe (bsd_init calls it behind offline-legacy-register) and the boot progress poll
 * NativeUfs calls from its root path. a configuration that links the real archive drops these. */
#include <pexpert/pexpert.h>

__attribute__((weak)) void
native_legacy_display_probe(void)
{
	kprintf("pdx203: native_legacy_display_probe: no display provider on this board yet\n");
}

__attribute__((weak)) void
boot_progress_poll(void)
{
}
