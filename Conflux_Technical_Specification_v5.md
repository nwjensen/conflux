# Conflux — Technical Specification v5

## 1. System Overview

Conflux is a **standalone, high-availability, local-first orchestration system** deployed in a Proxmox HA environment.

It:
- Ingests heterogeneous communication signals
- Normalizes them into time-aligned events
- Determines factual human-meaningful state
- Orchestrates redundant outbound communication
- Exposes read-only interfaces to family-facing systems

Conflux does not depend on AI services for correct operation.

---

## 2. Deployment Model

- Runs as redundant services in Proxmox HA
- No single point of failure
- State persisted across failover
- HA behavior is invisible to family users

---

## 3. Architectural Layers

### 3.1 Input Ingest Layer

Supported inputs:
- APRS (RF and/or APRS-IS)
- Meshtastic (USB, Wi-Fi, MQTT)
- MeshCore (serial or network)
- SDR monitoring (ham analog, DMR, P25 metadata)
- SMS delivery state
- CW detection (optional)

All adapters:
- Timestamp events
- Tag source and confidence
- Preserve provenance

---

### 3.2 Normalization Layer

Canonical event schema:

```json
{
  "timestamp": "ISO-8601",
  "source": "aprs | mesh | ham | dmr | p25 | sms | cw",
  "event_type": "position | message | presence | absence | delivery | transcript",
  "confidence": 0.0–1.0,
  "payload": {}
}
```

---

### 3.3 State Engine

Single authority for state.

Responsibilities:
- Maintain current state
- Track last-known observations
- Detect absence vs failure
- Require multi-source confirmation
- Accept explicit human override
- Persist state across HA failover

State transitions must be:
- Explicit
- Logged
- Explainable using observed data only

---

## 4. Orchestration Engine

### 4.1 Fan-Out Policy

Deterministic mapping of state to channels.

Example:
- 🟡 Delayed:
  - APRS: immediate
  - Mesh: immediate
  - SMS: next scheduled window
  - CW: optional
  - Voice: manual only

---

### 4.2 Scheduling Rules

- SMS is clock-gated (:00 / :30)
- Emergency bypasses scheduling
- Human override bypasses scheduling
- Duplicate sends suppressed unless state changes

---

## 5. Whisper Transcription Integration

### 5.1 Architecture

- Whisper runs as an external shared service (pve1)
- Conflux submits async, best-effort transcription jobs
- Conflux never blocks on transcription results

### 5.2 Constraints

- Transcription is observational only
- Transcripts do not influence state, signaling, or escalation
- Whisper failure must not degrade Conflux behavior

---

## 6. SMS Subsystem

- Outbound only
- Fixed trusted recipients
- Snapshot-style messages
- Delivery success/failure logged and re-ingested

---

## 7. Morse (CW) Signaling

CW is symbolic and factual.

| State | Pattern |
|-----|--------|
| OK | K |
| Delayed | D |
| Need Contact | R |
| Need Help | H |
| Emergency | SOS |

CW may be auto-keyed or manually keyed.

---

## 8. Interfaces

### 8.1 Family Command Hub API (Read-Only)
- /state
- /last_position
- /reachability
- /recent_messages
- /transmission_log

### 8.2 Ollama Interface (Read-Only)
- Query-only
- No control authority
- No inference authority in Phase 1

---

## 9. Logging and Audit

- All state transitions logged
- All outbound transmissions logged
- All delivery outcomes logged
- All logs replicated across HA nodes

---

## 10. Failure Modes

| Condition | Behavior |
|--------|----------|
| Single-node failure | Transparent failover |
| Input loss | Maintain last-known state |
| Whisper unavailable | No impact to core system |
| Partial delivery | Attempt alternate channels |
| Total silence | Maintain state, log absence |

---

## 11. Security and Trust

- Local-first
- No required cloud services
- Fixed trusted contacts
- Explicit opt-in for all outputs

---

## 12. Guiding Constraint

**If a statement cannot be supported by observed data, it must not be emitted.**
