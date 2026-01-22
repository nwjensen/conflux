# Conflux — Phase 1 Timer & Window Definitions

## Purpose

This document defines all **authoritative time-based windows** used by Conflux in Phase 1.

Goals:
- Deterministic behavior
- Predictable family experience
- No inference or interpretation
- Safe handling of silence and delay
- HA-safe restart behavior

All timers are **explicit constants**.
No adaptive or learned timing exists in Phase 1.

---

## Guiding Principles

- Time windows describe **expectation**, not danger
- Absence indicates **uncertainty**, not emergency
- Timers never directly trigger Emergency state
- Timers never bypass human override
- Restart does not reset elapsed context

---

## Global Time Concepts

| Term | Definition |
|-----|-----------|
| Observation Window | Expected interval between signals |
| Absence Window | Interval after which absence is noted |
| Extended Window | Interval after which escalation to Need Contact is permitted |
| Cooldown Window | Minimum time between repeated transmissions |
| Retention Window | How long observations are kept |

---

## APRS Timing

### Position Observation Window
- **Expected:** 5 minutes
- **Purpose:** Normal movement tracking

### Absence Window
- **10 minutes**
- Absence noted, no state change beyond 🟡 Delayed

### Extended Absence Window
- **20 minutes**
- Permits escalation to 🟠 Need Contact if previously moving

---

## LoRa Mesh (Meshtastic / MeshCore)

### Message Observation Window
- **Expected:** 10 minutes

### Absence Window
- **20 minutes**
- Logged as reduced reachability

### Extended Absence Window
- **40 minutes**
- Permits escalation to 🟠 Need Contact

---

## Ham Radio Activity

### Activity Observation Window
- **Passive**
- No expectation of periodic traffic

### Silence Window
- **None**
- Silence alone never triggers state change

### Whisper Transcription Window
- **Real-time enqueue**
- **Best-effort processing**
- No timeout impacts state

---

## Digital Voice (DMR / Fusion / D-STAR)

### Activity Observation Window
- **Passive**

### Silence Window
- **None**
- Used only for context, never for state

---

## SMS Delivery

### Scheduled Transmission Window
- **Top of hour (:00)**
- **Bottom of hour (:30)**

### Delivery Confirmation Window
- **5 minutes**
- Failure logged but does not escalate

### Retry Window
- **None**
- Retries only occur on next scheduled window

---

## CW (Morse)

### Transmission Interval
- **60 seconds** (if enabled)

### Silence Handling
- No inbound expectation
- Never affects state

---

## State-Specific Timing Behavior

### 🟢 OK
- No timers active
- Only observation windows apply

### 🟡 Delayed
- Absence windows active
- Extended windows allow escalation to 🟠 Need Contact

### 🟠 Need Contact
- Cooldown window applies to prevent spam
- No further escalation via timers

### 🔴 Need Help
- No automatic timers
- Only human override changes state

### 🚨 Emergency
- No timers
- Continuous signaling per channel rules

---

## Cooldown Windows

| Channel | Cooldown |
|-------|---------|
| APRS | 5 minutes |
| Mesh | 5 minutes |
| SMS | Schedule-gated |
| CW | Fixed interval |
| Voice | Manual only |

Cooldowns prevent duplicate messaging without state change.

---

## Retention Windows

| Data | Retention |
|----|----------|
| Event logs | 72 hours |
| State history | 30 days |
| Transcripts | 24 hours |
| Delivery logs | 7 days |

Retention is local-only.

---

## HA & Restart Rules

On restart or failover:
- Restore last-known timestamps
- Resume elapsed timers
- Do not re-trigger transmissions
- Do not escalate due to restart

---

## Explicit Prohibitions (Phase 1)

- No adaptive timing
- No ML-based window adjustment
- No urgency inference from speed
- No timer-based Emergency entry

---

## Guiding Rule

**Time describes expectation, never intent or danger.**
