#ifndef ZEPHLET_TESTS_SHELL_FUNCTIONAL_QUIET_H_
#define ZEPHLET_TESTS_SHELL_FUNCTIONAL_QUIET_H_

#include <stdbool.h>

#include "zlet_quiet_interface.h"

/**
 * @file
 * @brief Test-only `quiet` zephlet types — a type whose rpcs are all
 *        hidden from the shell, so its instance must not appear under
 *        the `zlet` root command.
 */

struct quiet_data {
	bool is_running;
	bool is_ready;
};

int quiet_init_fn(const struct zephlet *z);

#endif /* ZEPHLET_TESTS_SHELL_FUNCTIONAL_QUIET_H_ */
