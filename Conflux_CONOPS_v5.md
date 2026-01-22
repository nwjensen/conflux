# Conflux — General Concept of Operations (CONOPS) v5

## 1. Purpose

Conflux is a **standalone, local-first resilience and situational awareness system** designed to support an entire household during degraded, uncertain, or disrupted conditions.

The primary design audience is the **entire family**, with the **least-technical user (spouse)** defining usability, clarity, and tone.

Its purpose is to:
- Aggregate diverse communication and environmental inputs
- Translate observations into clear, factual, human-meaningful state
- Orchestrate calm, redundant outbound communication
- Reduce uncertainty and cognitive load across the household

Conflux is independent of Nodus. Nodus and similar systems may act as **inputs**, but Conflux does not depend on them.

Conflux is not an alert system.  
Conflux is not a prediction engine.  
Conflux is a *guardian narrator*.

---

## 2. Phase 1 Operating Constraint (Authoritative)

**Phase 1 operates strictly on observable facts.**

In Phase 1, Conflux:
- Reports what is observed
- Reports what is absent
- Reports what actions are being taken
- Avoids interpretation, inference, advice, or prediction

Preparedness recommendations, inference, and advisory logic are **explicitly excluded** in Phase 1.

---

## 3. Design Philosophy

### Core Principles
- Calm over urgency
- Redundancy over reliability
- State over events
- Predictability over cleverness
- Human understanding over technical transparency

If the system cannot be understood quickly by the least-technical family member, it is considered incorrect.

---

## 4. Operational Roles

### 4.1 Conflux (System Role)

Conflux performs three tightly scoped functions:

1. **Sense** — observe signals from multiple domains  
2. **Decide** — determine current factual human-relevant state  
3. **Signal** — express state redundantly across available channels  

Conflux supports **scheduled transmission** and always permits **immediate human override**.

---

### 4.2 Family Command Hub

The Family Command Hub is a passive, read-only interface for all family members.

It displays only:
- Current state
- Last known position and movement
- Reachability indicators
- Recent inbound messages
- Transmission history (what was sent, when)

It never displays:
- Frequencies
- Raw radio traffic
- Diagnostics
- Speculation or advice

---

### 4.3 Conversational Interface (Ollama)

Ollama acts as a calm explanatory interface that:
- Answers factual questions
- Explains observed system behavior
- Clarifies why messages were sent
- Reinforces calm through narration

Ollama:
- Has read-only access to Conflux
- Cannot escalate state
- Cannot speculate or advise in Phase 1

---

## 5. Human-Centered States

| State | Meaning |
|-----|--------|
| 🟢 OK | Moving or stationary, no concern |
| 🟡 Delayed | Safe but slowed or paused |
| 🟠 Need Contact | Attempting communication |
| 🔴 Need Help | Assistance required |
| 🚨 Emergency | Immediate help required |

State transitions require:
- Multi-source confirmation, or
- Explicit human action

---

## 6. Inputs (Observed Domains)

Conflux may observe:

- APRS (position, movement, status)
- LoRa mesh (Meshtastic / MeshCore)
- Ham analog activity (pattern-level)
- Digital voice activity (DMR, Fusion, D-STAR — pattern-level)
- Public safety radio activity (e.g., P25 via Nodus)
- SMS delivery success/failure
- Absence of expected signals

Additionally, Conflux may request **post-hoc transcription of ham audio** via an external Whisper service.  
Transcription is **observational only** and never influences state or signaling in Phase 1.

---

## 7. Outputs (Orchestrated Signaling)

### 7.1 Immediate Outputs
- APRS status updates
- LoRa mesh broadcasts
- Family Command Hub updates

### 7.2 Scheduled Outputs
- SMS messages sent only at:
  - Top of hour (:00)
  - Bottom of hour (:30)

### 7.3 Overrides
- Emergency state bypasses scheduling
- Human override may trigger immediate transmission

All outputs convey identical semantic meaning.

---

## 8. What Conflux Never Does (Phase 1)

- Predict outcomes
- Recommend actions
- Interpret speech
- Escalate autonomously
- Depend on AI services for correctness

---

## 9. Success Criteria

Conflux Phase 1 is successful if:
- Any family member understands system status in under 10 seconds
- Communication behavior is predictable and visible
- Silence is explained calmly
- Trust increases across the household

---

## 10. Guiding Sentence

**Conflux reports reality calmly and redundantly so the family never has to guess.**
