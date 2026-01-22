# Conflux — Phase 1 Canonical Message Catalog

## Purpose

This document defines the **authoritative Phase 1 message catalog** for Conflux.

Goals:
- Absolute clarity for non-technical family members
- Identical meaning across all transports
- Calm, factual, non-alarmist tone
- Zero interpretation or inference

Messages in this catalog are **fixed strings**.
They may only change if this document is updated.

---

## Message Design Rules (Phase 1)

- Short sentences
- Plain language
- No speculation
- No advice
- No emotional language
- No abbreviations (except OK)
- No technical terms
- No variable phrasing

Each state has:
- A **canonical meaning**
- Transport-specific renderings with identical semantics

---

## States Covered

- 🟢 OK
- 🟡 Delayed
- 🟠 Need Contact
- 🔴 Need Help
- 🚨 Emergency

---

## 🟢 OK

### Canonical Meaning
Normal movement or stopped briefly. No concern.

### APRS Status
```
OK. Moving normally.
```

### Mesh Broadcast
```
OK. Moving normally.
```

### SMS (Scheduled)
```
OK. Moving normally.
```

### CW
```
K
```

### Family Hub Display
```
Status: OK
Details: Moving normally
```

---

## 🟡 Delayed

### Canonical Meaning
Safe, but movement is slowed or paused.

### APRS Status
```
Delayed. Safe.
```

### Mesh Broadcast
```
Delayed. Safe.
```

### SMS (Scheduled)
```
Delayed. Safe.
```

### CW
```
D
```

### Family Hub Display
```
Status: Delayed
Details: Safe, slowed or stopped
```

---

## 🟠 Need Contact

### Canonical Meaning
Attempting to establish communication.

### APRS Status
```
Need contact.
```

### Mesh Broadcast
```
Need contact.
```

### SMS (Scheduled)
```
Trying to reach you.
```

### CW
```
R
```

### Family Hub Display
```
Status: Need Contact
Details: Attempting communication
```

---

## 🔴 Need Help

### Canonical Meaning
Assistance required, not immediately life-threatening.

### APRS Status
```
Need help.
```

### Mesh Broadcast
```
Need help.
```

### SMS (Immediate or Scheduled)
```
Need help. Not an emergency.
```

### CW
```
H
```

### Family Hub Display
```
Status: Need Help
Details: Assistance required
```

---

## 🚨 Emergency

### Canonical Meaning
Immediate assistance required.

### APRS Status
```
EMERGENCY.
```

### Mesh Broadcast
```
EMERGENCY.
```

### SMS (Immediate)
```
EMERGENCY. Need help now.
```

### CW
```
SOS
```

### Family Hub Display
```
Status: Emergency
Details: Immediate help required
```

---

## Transport Notes

### APRS
- Status text only
- No free-form messages in Phase 1
- Position accompanies status when available

### Mesh
- Broadcast only
- No threaded conversation
- No replies required

### SMS
- Clock-gated (:00 / :30)
- Emergency bypasses schedule
- Snapshot of current state only

### CW
- Symbolic only
- Repeated at fixed interval if enabled
- Never carries variable data

---

## Prohibited Content (Phase 1)

The following must never appear in messages:
- Causes
- Explanations
- Predictions
- Advice
- Emotional framing
- Apologies
- Urgency modifiers (except Emergency)

---

## Invariants

- Identical meaning across all channels
- Family must understand message in under 5 seconds
- No interpretation required
- Calm tone always

---

## Guiding Rule

**If a message requires explanation, it is not allowed in Phase 1.**
