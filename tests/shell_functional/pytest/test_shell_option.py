"""The `shell` rpc option: an rpc that sets it false is not registered
under its instance, and an instance whose rpcs all set it false is not
registered under `zlet` at all. Either way the lookup fails through
Zephyr's static tree, as in test_errors.py: the parent level prints its
help and real subcommand list.
"""

from __future__ import annotations

import re

from twister_harness import DeviceAdapter, Shell


def _out(shell: Shell, cmd: str) -> str:
	return "\n".join(shell.get_filtered_output(shell.exec_command(cmd)))


def _subcommands(out: str) -> list[str]:
	"""The names listed after `Subcommands:` in Zephyr's help output: only
	the `  <name>  :<help>` rows, never a wrapped help line or a prompt."""
	listing = out.split("Subcommands:", 1)[1]
	return re.findall(r"^\s+(\w+)\s*:", listing, flags=re.MULTILINE)


def test_hidden_rpcs_are_not_registered(dut: DeviceAdapter, shell: Shell):
	"""Hidden by the rpc body in the proto, and by the options file. Calling
	one prints the instance's help instead of reaching the rpc: its weak
	handler returns -ENOSYS, which the shell would report as `<rpc>: <rc>`."""
	assert shell.wait_for_prompt(), "shell prompt never appeared"

	for rpc in ("hidden_by_proto", "hidden_by_file"):
		out = _out(shell, f"zlet ui_main {rpc}")
		assert "Subcommands:" in out, out
		names = _subcommands(out)
		for shown in ("start", "stop", "get_status", "config", "get_config"):
			assert shown in names, out
		assert "hidden_by_proto" not in names, out
		assert "hidden_by_file" not in names, out
		assert f"{rpc}: -" not in out, out


def test_visible_rpcs_still_work(dut: DeviceAdapter, shell: Shell):
	"""Hiding rpcs renumbers nothing: the rest still reach their handler."""
	assert shell.wait_for_prompt(), "shell prompt never appeared"

	_out(shell, "zlet ui_main config blink_period_ms: 77")
	out = _out(shell, "zlet ui_main get_config")
	assert "blink_period_ms: 77" in out, out


def test_all_hidden_instance_is_not_registered(dut: DeviceAdapter, shell: Shell):
	assert shell.wait_for_prompt(), "shell prompt never appeared"

	out = _out(shell, "zlet quiet_main get_status")
	assert "Subcommands:" in out, out
	names = _subcommands(out)
	assert "quiet_main" not in names, out
	for instance in ("tick_fast", "tick_slow", "ui_main", "typelab_bench"):
		assert instance in names, out
