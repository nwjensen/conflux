# Conflux

> **Conflux reports reality calmly and redundantly so the family never has to guess.**

A standalone, local-first resilience and situational-awareness system for an
entire household during degraded, uncertain, or disrupted conditions. Conflux is
a *guardian narrator*: it **senses** signals from many domains, **decides** the
current factual human-relevant state, and **signals** that state redundantly
across every available channel.

This repository is the **Phase 1** implementation. Phase 1 operates strictly on
**observable facts** — it reports what is observed, what is absent, and what
actions were taken. No prediction, no inference, no advice. If a statement can't
be supported by observed data, it isn't emitted.

The concept documents this code implements live alongside it:
`Conflux_CONOPS_v5.md`, `Conflux_Technical_Specification_v5.md`, and the four
`Conflux_Phase1_*` specifications (state machine, message catalog, timers,
Family Command Hub wireframe).

---

## What it does today

- Tracks **_n_ subjects** (e.g. each family member), each with its own state,
  timers, reachability, and message history.
- Runs the Phase 1 **state machine** as a pure, auditable reducer:
  `🟢 OK → 🟡 Delayed → 🟠 Need Contact → 🔴 Need Help → 🚨 Emergency`.
- Escalates on **absence** (missing position updates) — never past Need Contact,
  never without prior movement. Emergency is reachable **only** by explicit human
  override.
- **Orchestrates** outbound signaling: APRS + Mesh immediately on state change,
  SMS clock-gated to `:00`/`:30` (Emergency bypasses), CW optional, all using the
  fixed **canonical message catalog**.
- Serves a **read-only Family Command Hub** (spouse-first web UI) plus a JSON API.
- Ships a **built-in input simulator** so the whole system runs end-to-end with
  no radios attached.

---

## Architecture

```
        ┌──────────── adapters (canonical events) ────────────┐
        │  APRS   Meshtastic   MeshCore   SDR   SMS   [sim]    │
        └───────────────────────┬─────────────────────────────┘
                                 ▼  CanonicalEvent
                        ┌─────────────────┐
                        │   service.py    │  ingest() / tick()
                        └───────┬─────────┘
             ┌──────────────────┼───────────────────┐
             ▼                  ▼                   ▼
     state_engine.py      orchestrator.py       db.py (append-only log)
     pure reducer         state → channels      events / transitions /
     + absence timers     + SMS scheduling      transmissions
             │                  │                   │
             └──────── views.py (read models) ──────┘
                                 ▼
                 FastAPI  ──  /api/*  ──  Family Command Hub (hub/)
```

**Design rules that make Phase 1 correct and HA-safe:**

- **State is derived, never stored.** Current state is the latest row in an
  append-only transition log. Restart/failover = re-derive from the log.
- **Timers are pure functions of persisted timestamps**, not in-memory
  countdowns — so elapsed time survives a restart automatically.
- **The state engine is a pure reducer** (`(context, event) → transition?`) with
  no I/O, unit-tested exhaustively against the transition table.
- **AI never has state authority.** (The Ollama narrator is a read-only Phase 2
  concern and is intentionally not wired into the correctness path.)

---

## Quickstart

### Docker Compose (recommended)

```bash
cp .env.example .env          # set CONFLUX_OVERRIDE_PIN at minimum
docker compose up --build -d
# open http://localhost:8080
```

This runs one Conflux service backed by PostgreSQL. It maps directly onto a
Proxmox HA active/passive VM/LXC later: single authority for state, no
split-brain, recovery by re-deriving from the log.

### Local (SQLite, no Docker)

```bash
make install     # venv + deps
make test        # 84 tests
make demo        # compressed-time demo on http://localhost:8080
```

`make run` uses real Phase 1 timing; `make demo` compresses time so the absence
ladder is visible in seconds.

---

## Try the demo

With `make demo` running (time compressed ~33×), open the Hub and:

1. Open a subject → **Toggle movement (sim)** to *park* them. Their position
   stream stops; watch them walk **OK → Delayed → Need Contact** over ~40s.
2. **Inject inbound message (sim)** → they recover to **Delayed** (reachability
   confirmed) and stay there.
3. **Override…** (PIN `0000` by default) → set **Emergency**; SMS bypasses the
   schedule and fans out immediately.

Or via the API:

```bash
curl localhost:8080/api/state
curl -X POST localhost:8080/api/sim/1/moving -H 'Content-Type: application/json' -d '{"moving": false}'
curl -X POST localhost:8080/api/override/1 -H 'Content-Type: application/json' \
     -d '{"state":"EMERGENCY","pin":"0000","immediate":true}'
```

---

## Real inputs: APRS-IS adapter

The built-in simulator is for development. To ingest **live** position reports,
enable the APRS-IS adapter — it subscribes to the APRS-IS network, matches each
packet's sender callsign to a subject, derives a `moving` flag (from reported
speed, or distance since the last fix), and feeds the same ingest path as any
other input. The core never learns APRS exists.

```bash
CONFLUX_APRS_ENABLED=true \
CONFLUX_APRS_CALLSIGN=YOURCALL \   # your amateur call; passcode -1 = receive-only
CONFLUX_SIMULATOR=false \
make run
```

Give each subject a real callsign (via `CONFLUX_SEED_SUBJECTS` or the DB) and the
adapter auto-builds an APRS-IS filter for them. Additional adapters (Meshtastic,
MeshCore, SDR) drop in behind the same `Adapter` interface in `conflux/adapters/`.

---

## API (read-only UI contract)

| Endpoint | Purpose |
|---|---|
| `GET /api/subjects` | List tracked subjects |
| `GET /api/state[/{id}]` | Current state (+ details, reason, since) |
| `GET /api/last_position/{id}` | Last known location + movement |
| `GET /api/reachability/{id}` | Per-channel seen/pending indicators |
| `GET /api/recent_messages/{id}` | Sent + received history |
| `GET /api/transmission_log/{id}` | What was sent, when, on which channel |
| `GET /api/timeline/{id}` | State changes + key facts over time |
| `POST /api/override/{id}` | Operator override (PIN protected) |
| `POST /api/sim/...` | Simulator controls (dev only) |

---

## How the code maps to the specs

| Spec document | Implementation |
|---|---|
| State Transition Table | `conflux/state_engine.py` |
| Timer & Window Definitions | `conflux/config.py`, `conflux/timers.py` |
| Canonical Message Catalog | `conflux/message_catalog.py` |
| Technical Spec (ingest/normalize/orchestrate) | `conflux/adapters/`, `conflux/service.py`, `conflux/orchestrator.py` |
| Family Command Hub Wireframe | `conflux/hub/`, `conflux/views.py` |
| CONOPS (states, roles, outputs) | the system as a whole |

---

## Configuration

All via environment variables — see `.env.example`. Highlights:
`CONFLUX_OVERRIDE_PIN`, `CONFLUX_DATABASE_URL`, `CONFLUX_TIME_SCALE`,
`CONFLUX_SMS_INTERVAL_SECONDS`, `CONFLUX_SIMULATOR`, `CONFLUX_SEED_SUBJECTS`.

---

## Explicitly out of scope in Phase 1

Prediction, recommendations, speech interpretation, autonomous escalation, and
any dependence on AI services for correctness. Real-radio adapters, the Ollama
narrator, Whisper transcript display, and true active/active HA are Phase 2+.

*If the least-technical family member can't understand system status in under 10
seconds, it is considered incorrect.*
