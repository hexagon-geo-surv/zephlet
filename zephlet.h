#ifndef MODULES_ZEPHLETS_SHARED_ZEPHLET_H
#define MODULES_ZEPHLETS_SHARED_ZEPHLET_H

#include <zephyr/kernel.h>
#include <zephyr/zbus/zbus.h>

struct zephlet {
	const char *name;
	struct {
		const struct zbus_channel *invoke;
		const struct zbus_channel *report;
	} channel;
	int (*init_fn)(const struct zephlet *self);
	void *api;
	void *const data;
};

#define ZEPHLET_DEFINE(_name, _init_fn, _api, _data)                                               \
	const STRUCT_SECTION_ITERABLE(zephlet, _name) = {                                          \
		.name = #_name,                                                                    \
		.channel =                                                                         \
			{                                                                          \
				.invoke = &CONCAT(chan_, _name, _invoke),                          \
				.report = &CONCAT(chan_, _name, _report),                          \
			},                                                                         \
		.init_fn = _init_fn,                                                               \
		.api = _api,                                                                       \
		.data = _data}

#define ZEPHLET_OBSERVE_REPORT(_zlet)                                                              \
	for (int _obs_done = (zbus_obs_set_enable(&CONCAT(msub_, _zlet, _report), true), 0);       \
	     !_obs_done;                                                                           \
	     zbus_obs_set_enable(&CONCAT(msub_, _zlet, _report), false), _obs_done = 1)

#endif /* MODULES_ZEPHLETS_SHARED_ZEPHLET_H */
