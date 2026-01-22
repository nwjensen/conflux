# Conflux — Phase 1 State Transition Table

## Purpose

This document defines the **authoritative Phase 1 state machine** for Conflux.

Phase 1 rules:
- Facts only
- No inference
- No advice
- No AI-driven escalation
- No automatic de-escalation without evidence

This table is intended to be **machine-implementable** and **human-auditable**.

---

## States (Fixed Set)

| State | Description |
|------|-------------|
| 🟢 OK | Normal movement or stationary, no concern |
| 🟡 Delayed | Safe but slowed, paused, or stopped |
| 🟠 Need Contact | Attempting communication, no confirmation |
| 🔴 Need Help | Assistance required, non-immediate |
| 🚨 Emergency | Immediate assistance required |

Only Conflux may hold state.  
Only defined transitions are permitted.

---

## Evidence Types

Phase 1 evidence is **observable only**.

| Evidence | Description |
|--------|-------------|
| Position Update | APRS or equivalent location update |
| Movement | Change in position over time |
| Status Message | Explicit human-sent status |
| Message Delivery | Confirmed outbound or inbound message |
| Absence | Expected signal not observed within window |
| Human Override | Manual operator input |
| System Action | Conflux-initiated transmission |

No semantic interpretation is permitted.

---

## Global Transition Rules

- **Multi-source confirmation required** unless human override
- **Absence alone may not escalate beyond 🟠 Need Contact**
- **Emergency may only be entered via explicit human action**
- **Automatic downgrade requires positive evidence**
- **System restart must restore last-known state**

---

## State Transition Matrix

### 🟢 OK

| Trigger | Condition | Next State | Notes |
|------|----------|-----------|------|
| Position update | Movement observed | 🟢 OK | Refresh timestamp |
| No movement | Within normal window | 🟢 OK | No change |
| Absence | Exceeds expected window | 🟡 Delayed | Only if prior movement existed |
| Human override | Mark delayed | 🟡 Delayed | Manual |
| Human override | Need contact | 🟠 Need Contact | Manual |
| Human override | Need help | 🔴 Need Help | Manual |
| Human override | Emergency | 🚨 Emergency | Manual only |

---

### 🟡 Delayed

| Trigger | Condition | Next State | Notes |
|------|----------|-----------|------|
| Position update | Movement resumes | 🟢 OK | Positive evidence |
| Status message | Explicit safe/delayed | 🟡 Delayed | Refresh |
| Absence | Continues | 🟠 Need Contact | After extended window |
| Human override | OK | 🟢 OK | Manual |
| Human override | Need contact | 🟠 Need Contact | Manual |
| Human override | Need help | 🔴 Need Help | Manual |
| Human override | Emergency | 🚨 Emergency | Manual only |

---

### 🟠 Need Contact

| Trigger | Condition | Next State | Notes |
|------|----------|-----------|------|
| Message received | Any channel | 🟡 Delayed | Downgrade requires confirmation |
| Position update | Movement observed | 🟢 OK | Strong evidence |
| Absence | Continues | 🟠 Need Contact | No auto-escalation |
| Human override | Delayed | 🟡 Delayed | Manual |
| Human override | Need help | 🔴 Need Help | Manual |
| Human override | Emergency | 🚨 Emergency | Manual only |

---

### 🔴 Need Help

| Trigger | Condition | Next State | Notes |
|------|----------|-----------|------|
| Human override | Delayed | 🟡 Delayed | Manual only |
| Human override | OK | 🟢 OK | Manual only |
| Human override | Emergency | 🚨 Emergency | Manual |
| Message received | Confirmation of help | 🔴 Need Help | No auto-downgrade |

Automatic downgrade is **not permitted**.

---

### 🚨 Emergency

| Trigger | Condition | Next State | Notes |
|------|----------|-----------|------|
| Human override | Need help | 🔴 Need Help | Manual only |
| Human override | Delayed | 🟡 Delayed | Manual only |
| Human override | OK | 🟢 OK | Manual only |

Emergency state **cannot be exited automatically**.

---

## Scheduled Transmission Interaction

- State does **not** change due to scheduled SMS
- Scheduled transmissions reflect current state only
- Emergency bypasses schedule but does not change logic

---

## HA & Restart Behavior

On restart or failover:
- Restore last-known state
- Resume timers
- Do not emit new transmissions unless triggered
- Do not escalate due to restart

---

## Invariants (Must Never Be Violated)

- Emergency requires explicit human action
- Absence never implies danger
- AI output never changes state
- State transitions are monotonic unless evidence exists
- Calm behavior overrides clever behavior

---

## Guiding Rule

**If a transition cannot be justified with observable evidence, it must not occur.**
