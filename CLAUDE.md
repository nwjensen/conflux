# Working on Conflux in this container

**This checkout IS the live deployment.** It is not a dev sandbox. You are in LXC
CT 200 (`conflux`) on the Proxmox node pve2. Changes here affect the running
system that the household actually depends on.

See `README.md` for architecture and Phase 1 design rules, and the
`Conflux_*.md` spec documents for the state machine, message catalog, and timers.
This file covers only the deployment facts that live outside the repo.

## Live state — treat as production data

Postgres 17 (local, `127.0.0.1:5432`) holds the **append-only** event, transition,
and transmission log. Because Conflux *derives* current state rather than storing
it, that log is the system's entire memory and history.

- **Do not** write to the database directly.
- **Do not** call the `/api/sim/*` endpoints, or enable `CONFLUX_SIMULATOR`,
  against this instance — simulated events become permanent real transitions.
- **Do not** reseed subjects. `CONFLUX_SEED_SUBJECTS` is for first boot only.

Real subjects are live and one is fed by the aprs.fi poller. Reads
(`/api/state`, `/api/timeline/{id}`, …) are safe.

## Restarting after a change

uvicorn runs under systemd **without** `--reload`, so edits do nothing until:

```
systemctl restart conflux
systemctl status conflux --no-pager
journalctl -u conflux -n 50 --no-pager
```

Service: `conflux.service` → `/opt/conflux/.venv/bin/python -m uvicorn
conflux.main:app --host 0.0.0.0 --port 8080`, running as the **`conflux`** user.
You are likely root, so files you create will be root-owned — harmless for the
service (it only reads them), but it shows up in `git status`.

## Configuration lives outside the repo

`/etc/conflux/conflux.env` (mode 0600, root-owned, loaded via the unit's
`EnvironmentFile`). It is **not** in git and has no copy anywhere else — do not
overwrite it, and never commit its contents. Keys:

`CONFLUX_DATABASE_URL`, `CONFLUX_OVERRIDE_PIN`, `CONFLUX_SIMULATOR`,
`CONFLUX_APRS_ENABLED`, `CONFLUX_APRS_CALLSIGN`, `CONFLUX_APRS_PASSCODE`,
`CONFLUX_SEED_SUBJECTS`

`.env.example` in the repo documents them; the Docker Compose path is not what
runs here.

## Networking

- Container IP `10.10.2.101/24`, app on `0.0.0.0:8080`.
- Public URL `http://conflux.lan.nodusrf.com` — reverse-proxied by Caddy in
  CT 132. HTTP only, LAN only.
- Postgres is bound to localhost and is not reachable off-container.

## Git

Remote is `https://github.com/nwjensen/conflux.git` (public). Auth is via `gh`
(`gh auth git-credential`); identity is `nwjensen <nwjensen@gmail.com>`, matching
the existing history. GitHub is the source of truth for code — historically this
checkout only ever received `git pull --ff-only origin main`. Committing here is
fine, but push so the container never becomes the only copy of a change.

## Tests

```
.venv/bin/python -m pytest -q
```

The state engine is a pure reducer and is unit-tested against the transition
table — keep it pure and keep those tests exhaustive. Per the Phase 1 rules,
**AI never has state authority**: do not wire a model into the correctness path,
and do not emit any statement that observed data cannot support.
