# xray-stats

Bash + Python tooling that enables [xray-core][xray]'s stats API on a
server, then collects per-user uplink/downlink bytes via cron and stores
them as plain text files under `$TRAFFIC_DIR/<user>/<down|up>/<date>`.

[xray]: https://github.com/XTLS/Xray-core

## Layout

- `enable-stats.py` — position-tracking JSONC editor that idempotently
  bootstraps the xray stats setup (`stats`, `api` block, dokodemo-door
  inbound, routing rule, policy flags). Preserves comments and trailing
  commas in the original config. Stdlib-only.
- `enable-stats.sh` — wrapper: makes a timestamped `.bak`, calls the
  Python editor, restarts xray only when changes were applied (exit 0
  = changes, exit 5 = no-op).
- `stats-collect` — cron every 2 min. `xray api statsquery -server
  "$API_SERVER" -reset`, then appends per-user bytes to today's file.
  Date is captured once per run to avoid attributing bytes to the
  wrong day across midnight.
- `stats-query` — `stats-query [<date>|<YYYY-MM>] [<user-glob>]`. Sums
  files for the given date or month, prints `user down-mb up-mb` (or
  raw bytes with `--plain`).
- `stats-shrink` — cron at `:29` and `:59`. Replaces each day's file
  with a single summed value to bound disk growth.
- `stats-utils.sh` — sourced helpers. Exposes `TRAFFIC_DIR`,
  `API_SERVER`, and `sum-num-file`.
- `stats-to-user-down-up.jq` — emits tab-separated `<user>\t<down>\t<up>`.
- `install.sh [<traffic-data-dir> [<api-server>]]` — installs to
  `/usr/local/bin`, writes config files, merges entries into the user's
  crontab without overwriting, then runs `enable-stats.sh`.
- `xray-stats.cron` — cron schedule for collect + shrink.
- `tests/test_enable_stats.py` — 16-test pytest suite for the JSONC
  editor. Self-contained; no dependency on gitignored fixtures.

## Config files (system-level)

- `/usr/local/etc/xray-stats/directory` — traffic data dir
- `/usr/local/etc/xray-stats/server` — `host:port` of xray's stats API

## Tests

```sh
.venv/bin/pytest tests/
```

Pytest lives in `.venv/` (gitignored). Tests are end-to-end via
subprocess; they construct configs inline so a fresh clone runs them.

## Conventions

- Shell scripts: `#!/usr/bin/env bash` + `set -eo pipefail`, shellcheck-clean.
- Commit messages use conventional prefixes (`feat:`, `fix:`, `perf:`,
  `test:`). Short subject, why-focused body.
- `*.json` is gitignored — local configs stay out of git.
- `enable-stats.py` is stdlib-only (no third-party Python deps); the
  install path is `bash → python3 enable-stats.py`, so anything pip
  would add must be justified.

## Recent work

- **`enable-stats.py` replaces `jq | sponge`.** The old script piped a
  jq transform into sponge, which would silently corrupt the xray
  config if jq exited non-zero mid-output. The new editor parses
  JSONC (handles `//`, `#`, `/* */` comments and trailing commas),
  plans surgical text inserts, and writes via `mktemp + mv`. Idempotent
  — re-running on a fully-configured file makes zero changes.
- **Full API bootstrap.** `enable-stats` now adds not just policy and
  services but also the `dokodemo-door` inbound on `127.0.0.1:10085`
  tagged `api`, plus the prepended `inboundTag:["api"] → outboundTag:
  "api"` routing rule. Without these a fresh xray config has nowhere
  for `xray api` to connect.
- **`stats-collect -server "$API_SERVER"`.** Previously `xray api
  statsquery` was invoked with no `-server` flag, so it hit xray's
  built-in default (`127.0.0.1:8080`) instead of the dokodemo-door
  endpoint enable-stats configures. The address now comes from
  `/usr/local/etc/xray-stats/server`, written by `install.sh`.
- **Shellcheck cleanup & safety hardening.** Quoted `$0`/`$1`, captured
  `date +%F` once in stats-collect to avoid a midnight race, switched
  jq output to tab-separated so usernames with spaces don't break
  `read`, replaced destructive `crontab < xray-stats.cron` with a
  merge that strips only existing `stats-` lines and preserves the
  rest of the user's crontab.
- **16-test pytest suite** covers idempotency, JSONC comment
  preservation, partial configs, duplicate-inbound/rule avoidance,
  prepending behavior, and backup semantics.
