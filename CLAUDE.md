# Zephlet Infrastructure v0.2.1

Ports+Adapters on Zephyr/zbus. Zephlets=domain logic (no direct deps), adapters=bridge zephlet reports→invokes, main=lifecycle.

## Commands (west)

- `west zephlet new [-n -d -a]` — interactive w/o args
- `west zephlet new-adapter` — always interactive
- `west zephlet gen ZEPHLET` — regen interfaces (needs `build/modules/<z>_zephlet`)
- `west config zephlet.{zephlets-dir,adapters-dir} <path>` — default `<project>/src/{zephlets,adapters}/`, falls back to root dirs
- impl: `west/zephlet_commands.py` via `west-commands.yml`. Deps checked: copier, proto-schema-parser, jinja2. Workspace paths auto-resolved from manifest.

## Channels

Per zephlet: `chan_<z>_invoke` (cmds), `chan_<z>_report` (status/events). Zephlets listen sync/async, publish to report.

## Zephlet files

- **VCS:** `zlet_<n>.proto`, `zlet_<n>.c` (after bootstrap), CMakeLists.txt, Kconfig, module.yml
- **Generated:** `zlet_<n>_interface.{h,c}` (data/api/dispatcher/channels/blocking-impls/`<z>_set_implementation`), `zlet_<n>.h` (async report helpers), `.pb.{h,c}`
- **Bootstrap:** CMake auto-gens `.c` via `--impl-only` if missing; then hand-edit only.
- `_interface.h` exports: `<z>_data` (state+spinlock), `<z>_context` (self+response+timeout), `<z>_api` (int (*fn)(<z>_context*)), blocking call decls.
- `.c`: init_fn sets is_ready, api impls return int + fill `ctx->response`, K_SPINLOCK. Ends `ZEPHLET_DEFINE(<z>, init_fn, &api, &data)`. Interface publishes. Use `<z>_report_*_async()` only for events/timers.
- Shared: `struct zephlet` + `ZEPHLET_DEFINE()` + `ZEPHLET_CALL_OK()` via `STRUCT_SECTION_ITERABLE`.

## Blocking API (gRPC-style)

All unary RPCs blocking. `<report> <z>_<cmd>([params], k_timeout_t)` returns by value. `ZEPHLET_CALL_OK(r)` = `r.has_result && r.result.return_code==0`. Errors: -ETIMEDOUT/-EBUSY/-EALREADY or app errno in `return_code`. `result.invoke_tag` = which RPC.

Async events (impl-side): `int <z>_report_*_async([data], k_timeout_t)` — has_result=false.

Advanced listener pattern: `ZEPHLET_OBSERVE_REPORT` + `wait_report` still available.

## Adapters

Listen zephlet report → invoke another zephlet. Zero direct coupling. `ZBUS_ASYNC_LISTENER_DEFINE` + `ZBUS_CHAN_ADD_OBS(prio=3)`. Kconfig toggleable.
`base_adapter.c`: `LOG_MODULE_REGISTER(adapter, CONFIG_ADAPTERS_LOG_LEVEL)`. Others: `LOG_MODULE_DECLARE(...)`.
Includes: interface headers only (no .pb.h). Order: interface, blank, zephyr, blank.

## Protobuf (nanopb)

`MsgZlet<Z> { Config, Events, Invoke{oneof}, Report{oneof} }`. Import `zephlet.proto` for Empty/ZephletStatus. Options: `anonymous_oneof=true`, `long_names=false` (→ `MSG_TICK_INVOKE` not `MSG_ZLET_TICK_MSG_ZLET_TICK_INVOKE`). Query RPCs (get_status/get_config) return reports. Proto collected via `PROTO_FILES_LIST`→`zephyr_nanopb_sources()`. Don't edit generated.

**Lifecycle reserved:** Invoke 1-6 = start, stop, get_status, config, get_config, get_events. Report 1-3 = status, config, events. Custom: Invoke 7+, Report 4+. `validate_field_numbers()` enforces at build time (duplicates+standard-name-at-reserved fatal; gaps warn).

**Result:** `ZephletResult {correlation_id, return_code, invoke_tag}` at `optional result = 999` in Invoke/Report. Blocking calls auto-fill correlation_id + invoke_tag. `return_code` = POSIX errno (0=ok). `has_result` separates responses from async events.

**Status:** `MsgZephletStatus {is_running, is_ready}`. is_ready set once by init (SYS_INIT); is_running toggled by start/stop.

**Generated C types:** `struct msg_<z>_{invoke|report|config}`, tags `MSG_<Z>_INVOKE_<CMD>_TAG`, oneof selector `which_<name>`.

## Build system

- `zephyr_zephlet_define(<name> [INCLUDE_DIRS ...] [SRCS ...])` — single-line `CMakeLists.txt` per zephlet. Wraps `CONFIG_ZEPHLET_<N>` guard. Does proto gen + codegen + interface lib + zephyr lib.
- `zephyr_zephlet_generate(<proto>)` — generates interfaces, bootstraps `.c` via `--impl-only` if missing.
- `shared_zephlet` exposes `${CMAKE_BINARY_DIR}/zephlets` globally for .pb.h. Each zephlet: `zephyr_include_directories(${CMAKE_CURRENT_BINARY_DIR})` after generate. Interface lib propagation via `zephyr_interface_library_named()`.
- Proto collection: append to `PROTO_FILES_LIST` global, root→`zephyr_nanopb_sources()`.
- Py deps: proto-schema-parser, jinja2.

## Workflows

**New zephlet:** `west zephlet new` → copier writes 5 files → edit `.proto` (Config/Events/RPCs) → `just b` (bootstraps `.c`) → fill TODOs → add to root `EXTRA_ZEPHYR_MODULES` → `CONFIG_ZEPHLET_<Z>=y` → rebuild.

**Modify:** edit `.proto` → auto-regen interfaces (never overwrites `.c`) → update `.c` → build.

**New adapter:** `west zephlet new-adapter` → prompts origin/dest + report fields → fill TODOs → `CONFIG_<O>_TO_<D>_ADAPTER=y`. Auto-writes `.c` + Kconfig + CMakeLists entries. Origin Report parsed + Dest Invoke parsed (Invoke names → TODO hints).

## Kconfig

`CONFIG_ZEPHLET_<Z>=y`, `CONFIG_ZEPHLET_<Z>_LOG_LEVEL_DBG=y`, `CONFIG_<O>_TO_<D>_ADAPTER=y`.

## Naming

| Elem | Pattern |
|---|---|
| Source | `zlet_<n>.{proto,c}` |
| Generated | `zlet_<n>_interface.{h,c}`, `zlet_<n>.h` |
| Adapter file | `<Origin>+<Dest>_zlet_adapter.c` (CamelCase) |
| Adapter fn | `<origin>_to_<dest>_adapter` |
| Channels | `chan_<z>_{invoke,report}` |
| Listeners | `lis_<z>`, `lis_<o>_to_<d>_adapter` |
| Messages | `msg_<z>_{invoke,report,config}` |
| Structs | `<z>_{data,api,context}` |
| API fns | inline `<z>_<cmd>()`, impl `static int <cmd>(<z>_context*)` |
| Config | `CONFIG_ZEPHLET_<Z>`, `CONFIG_<O>_TO_<D>_ADAPTER` |

## Data flow

Init: `init_fn` → `init()` (is_ready=1) → `set_implementation()`. Blocking: `<z>_start(t)` → sem_take → correlation_id → pub invoke (result+invoke_tag) → `wait_report_sync` (filters tag+invoke_tag+corr_id) → sem_give → return report. Async: timer → `report_*_async()` (no result) → observers see `has_result=false`. Errors: -EBUSY (sem), -ETIMEDOUT (wait), app errno in return_code.

## Principles

zbus-only coupling. Single return (`ret`+`goto end`; multiple allowed for guards). No direct deps (except inline API). K_SPINLOCK for state. Auto-discover via `STRUCT_SECTION_ITERABLE`.

## Code generation

Scripts: `codegen/generate_zephlet.py`, `codegen/generate_adapter.py`. Templates: `codegen/templates/` (6 jinja2: zephlet.h→_interface.h, zephlet.c→_interface.c, zephlet_priv.h→.h, zephlet_impl.c→.c, adapter.c, adapter_kconfig). Filters: `camel_to_snake`, `upper`, `lower`. Copier: `zephyr_zephlet_template/`.

**Flags:** `--generate-impl` / `--no-generate-impl` / `--impl-only` (bootstrap).
**Parser:** proto-schema-parser extracts service/invoke/report/config oneofs → api func ptrs + dispatcher switch/case.
**RPC validation:** return type must match Report oneof field (`MsgZephletStatus`→status, `Config`→config, `Events`→events).
**Helper header `<z>.h`:** `report_*_async()` only. Interface layer owns correlated publishing.
**Adapter gen:** scans protos, parses Report/Invoke oneofs, writes adapter.c+Kconfig (before `module =`)+CMakeLists (after last `zephyr_library_sources`), manual fallback. Interactive=selected report fields, non-interactive=all.
