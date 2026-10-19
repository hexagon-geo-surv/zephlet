#include "zlet_quiet.h"

int quiet_init_fn(const struct zephlet *z)
{
	struct quiet_data *d = z->data;

	d->is_running = false;
	d->is_ready = true;
	return 0;
}
