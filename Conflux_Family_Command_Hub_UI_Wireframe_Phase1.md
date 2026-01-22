# Conflux — Family Command Hub UI Wireframe (Phase 1)

## Purpose

Define a **spouse-first** (least-technical user) UI wireframe for the Family Command Hub.

Phase 1 constraints:
- Facts only
- No advice / recommendations
- No speculation
- No diagnostics
- No technical details (frequencies, talkgroups, RSSI, CPU, etc.)
- Read-only interface

Primary goal:
- Any family member can understand current status in **under 10 seconds**.

---

## Information Architecture (Top-Level)

The UI has **one primary screen** with optional drill-in views:

1. **Home / Status** (default)
2. **Messages** (inbound + outbound history)
3. **Reachability** (simple indicators)
4. **Timeline** (state changes + key events)

No other pages in Phase 1.

---

## Visual Language

### States (Required)
- 🟢 OK
- 🟡 Delayed
- 🟠 Need Contact
- 🔴 Need Help
- 🚨 Emergency

### Time (Required)
All timestamps displayed as:
- **Local time** (e.g., `7:30 PM`)
- With relative freshness (e.g., `7 min ago`)

### Clarity Rules
- One concept per line
- No scrolling required for essential info
- Avoid abbreviations except “OK”
- Use plain labels: “Last update”, “Last known location”, “Sent”, “Received”

---

## Screen 1: Home / Status (Default)

### Layout (Mobile-first, works on tablet/desktop)

```
┌───────────────────────────────────────────────┐
│ CONFLUX                                        │
│ Family Status                                  │
├───────────────────────────────────────────────┤
│ [STATE CHIP]  🟡 DELAYED                        │
│ Details: Safe, slowed or stopped               │
│ Last update: 7:30 PM (7 min ago)               │
├───────────────────────────────────────────────┤
│ Location                                       │
│ Last known: 123 Main St, Omaha                 │
│ Movement: Stopped / Moving / Unknown           │
│ Updated: 7:28 PM (9 min ago)                   │
├───────────────────────────────────────────────┤
│ Reachability (simple)                          │
│ APRS:   ✓ Seen recently   | Last: 7:28 PM      │
│ Mesh:   ✓ Seen recently   | Last: 7:26 PM      │
│ SMS:    ? Pending/Unknown | Last sent: 7:30 PM │
│ Voice:  Manual only                              │
├───────────────────────────────────────────────┤
│ Latest Messages                                │
│ • Received: “OK. Moving normally.” 7:22 PM     │
│ • Sent:     “Delayed. Safe.”     7:30 PM       │
├───────────────────────────────────────────────┤
│ Buttons                                        │
│ [View Messages]  [View Timeline]  [Override*]  │
└───────────────────────────────────────────────┘
```

\*Override visibility is configurable:
- Default: visible to operator only (PIN-protected)
- Family can see it only if enabled

### Required Elements
- Current state (large, unmistakable)
- One-line state detail (from Message Catalog)
- Last update time
- Last known location + movement label
- Reachability block (simple)
- Latest inbound/outbound lines
- Navigation buttons

### Prohibited Elements (Phase 1)
- Maps with layers, heatmaps, radio data
- Any “advice” text
- Any mention of Whisper/AI
- Any “confidence scoring” beyond seen/not seen

---

## Screen 2: Messages

Purpose:
- Show clear history of what was **sent** and **received**

### Layout

```
┌───────────────────────────────────────────────┐
│ Messages                                      │
├───────────────────────────────────────────────┤
│ Filters: [All] [Sent] [Received]              │
├───────────────────────────────────────────────┤
│ 7:30 PM  Sent (SMS)        “Delayed. Safe.”   │
│ 7:26 PM  Received (Mesh)   “OK. Moving normally.”│
│ 7:00 PM  Sent (SMS)        “OK. Moving normally.”│
│ 6:58 PM  Sent (APRS)       “OK. Moving normally.”│
│ …                                             │
└───────────────────────────────────────────────┘
```

### Rules
- Transport names are allowed (SMS / APRS / Mesh / CW) but no technical detail.
- Messages must match the Phase 1 Message Catalog exactly.
- If a transport fails, show a simple label: “Delivery not confirmed”.

---

## Screen 3: Reachability

Purpose:
- Give a spouse-friendly “can we reach him?” view.

### Layout

```
┌───────────────────────────────────────────────┐
│ Reachability                                  │
├───────────────────────────────────────────────┤
│ APRS     ✓ Seen recently     Last: 7:28 PM     │
│ Mesh     ✓ Seen recently     Last: 7:26 PM     │
│ SMS      ? Pending/Unknown   Last sent: 7:30 PM│
│ CW       — Optional          (if enabled)      │
│ Voice    — Manual only                          │
├───────────────────────────────────────────────┤
│ Notes                                         │
│ “Pending/Unknown” means we did not receive a   │
│ confirmation. It does not mean failure.        │
└───────────────────────────────────────────────┘
```

### Rules
- This screen may include **one** factual clarifier:
  - “Pending/Unknown means not confirmed.”
- No speculation or advice.

---

## Screen 4: Timeline

Purpose:
- Calmly show state changes and key facts over time.

### Layout

```
┌───────────────────────────────────────────────┐
│ Timeline                                      │
├───────────────────────────────────────────────┤
│ 7:30 PM  State: 🟡 Delayed                     │
│         Sent (SMS): “Delayed. Safe.”           │
│ 7:28 PM  Position update received              │
│ 7:00 PM  State: 🟢 OK                          │
│         Sent (SMS): “OK. Moving normally.”     │
│ …                                             │
└───────────────────────────────────────────────┘
```

### Rules
- Show only:
  - state changes
  - position update received (fact only)
  - transmissions sent (fact only)
- No interpretation.

---

## Override UI (Operator Only)

If enabled, “Override” enters an operator-only screen (PIN protected).

### Allowed actions (Phase 1)
- Set state to one of: OK / Delayed / Need Contact / Need Help / Emergency
- Trigger immediate transmission (bypass schedule) for current state
- Cancel pending scheduled transmission

### Required safeguard
- Confirmation prompt:
  - “This will send messages now.”

---

## Accessibility & Usability Requirements

- Works on mobile and tablet
- Large state label and icon
- High contrast by default
- No scrolling needed for Home screen essentials
- All text is plain and readable at a glance

---

## Data Requirements (UI Contract)

The UI may only consume read-only endpoints:
- `/state`
- `/last_position`
- `/reachability`
- `/recent_messages`
- `/transmission_log`
- `/timeline` (derived server-side)

No other API access in Phase 1.

---

## Phase 2+ (Explicitly Out of Scope)

- Preparedness recommendations
- Confidence scoring beyond seen/not seen
- Whisper transcript display
- Multi-user roles/permissions beyond a simple PIN

---

## Guiding Rule

**If the spouse cannot explain what the screen means in one sentence, it is too complex.**
