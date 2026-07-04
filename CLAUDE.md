# Project Instructions for AI Agents

**phyn_local** — a HACS-installable Home Assistant custom integration that monitors and controls a **Phyn Plus smart water shutoff valve entirely over the LAN** (no cloud). Every other HA Phyn integration is cloud-only; this is the first local-polling one.

> **⚠️ The beads workflow is mandatory.** Read `AGENTS.md` before doing anything — all work must go through `bd ready` / `bd update --claim` / `bd close`, and the model/delegation cost policy there applies to every session.

## How the device is controlled

The Phyn Plus exposes a **JNAP HTTP API on port 80** of the LAN (endpoints and fields in `PROTOCOL.md`, exact request shapes in `probe_jnap.sh`, a real state dump in `device_state.local.json` which is gitignored):

- All calls: `POST http://<host>/JNAP/` with `X-JNAP-Authorization: Basic base64("admin:admin")`, `X-JNAP-Action: <urn>`, JSON body
- `core/GetDeviceInfo` `{}` → identity (serial, MAC, firmware)
- `attribute/get` **empty body `{}`** → full state `{system, product, stats}` (pressure, temp, flow, consumption, valve state, RSSI, leak/freeze detectors) — the coordinator polls only this, once per cycle
- `shutoff/SetShutoffValveState` `{"state":"Open"|"Close"}` → **moves a real water valve; never call without explicit user consent**

Device IP is DHCP and changes; MAC OUI is `28:F5:37` (DHCP discovery matcher `28F537*`). Unique ID is the device **serial**.

## Layout

```
custom_components/phyn_local/   # the integration (api.py, coordinator.py, config_flow.py, valve.py, sensor.py, binary_sensor.py, …)
tests/                          # pytest-homeassistant-custom-component suite
hacs.json, README.md            # HACS packaging
.github/workflows/              # hassfest + HACS validation CI
```

## Build & Test

```bash
pip install pytest-homeassistant-custom-component
pytest                                          # unit tests (config flow, coordinator)
python -m json.tool custom_components/phyn_local/manifest.json   # sanity-check JSON
# hassfest runs in CI (.github/workflows/hassfest.yaml)
```

Live smoke-testing needs the device's current DHCP IP (find it by OUI `28:F5:37` or the Google Home app). Read-only probes via `./probe_jnap.sh <ip>` are always safe.

## Conventions

- HA modern patterns: `entry.runtime_data` (typed `ConfigEntry[PhynData]`, not `hass.data`), `DataUpdateCoordinator` + `CoordinatorEntity`, `ValveEntity` with `reports_position=False`, `iot_class: local_polling`, `integration_type: device`
- Config flow: `unique_id` = device serial; `_abort_if_unique_id_configured(updates={CONF_HOST: host})` so DHCP discovery updates the IP on lease changes
- Unit constants from `homeassistant.const`; device values are imperial (PSI, °F, gal)

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
