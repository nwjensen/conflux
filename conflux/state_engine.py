"""The Phase 1 state engine — a pure, auditable reducer.

Two pure functions decide *all* state changes:

  * :func:`apply_event`    — event-driven transitions (override, movement, message)
  * :func:`evaluate_timers` — absence-driven escalation (OK -> Delayed -> Need Contact)

Both take an immutable :class:`SubjectContext` (derived from persisted facts) and
return an :class:`Optional[Transition]`. No database, no clock beyond the ``now``
argument, no AI. This mirrors ``Conflux_Phase1_State_Transition_Table`` exactly.

Invariants enforced here:
  * Emergency may only be entered by explicit human action.
  * Absence alone never escalates beyond Need Contact.
  * Need Help / Emergency never downgrade automatically.
  * Every transition carries a reason grounded in observed data.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from . import config
from .models import CanonicalEvent, EventType, Source, State


@dataclass(frozen=True)
class SubjectContext:
    """A snapshot of everything the reducer needs, derived from stored facts."""

    subject_id: int
    state: State
    state_entered_at: datetime

    # Last-seen timestamps per relevant signal (None == never observed).
    last_position_at: Optional[datetime] = None
    last_movement_at: Optional[datetime] = None
    last_aprs_at: Optional[datetime] = None
    last_mesh_at: Optional[datetime] = None
    last_inbound_message_at: Optional[datetime] = None

    # Cooldown bookkeeping for the Need Contact state (prevents escalation spam).
    last_escalation_at: Optional[datetime] = None


@dataclass(frozen=True)
class Transition:
    """A justified move from one state to another."""

    subject_id: int
    from_state: State
    to_state: State
    trigger: str      # short machine tag: "override" | "movement" | "message" | "absence"
    reason: str       # human-auditable, observed-data-only sentence
    at: datetime

    @property
    def is_change(self) -> bool:
        return self.from_state != self.to_state


def _elapsed(now: datetime, since: Optional[datetime]) -> Optional[float]:
    if since is None:
        return None
    return (now - since).total_seconds()


# States that will not downgrade or change on their own — only human override
# can leave them. (State table: Need Help / Emergency have no automatic exits.)
_HUMAN_ONLY_EXIT = {State.NEED_HELP, State.EMERGENCY}


def apply_event(ctx: SubjectContext, event: CanonicalEvent, now: datetime) -> Optional[Transition]:
    """Return a transition for an incoming event, or ``None`` for no change.

    Only these events can move state:
      * override  -> any target state (the only path into Emergency)
      * position with movement -> OK (from OK/Delayed/Need Contact only)
      * inbound message while Need Contact -> Delayed (confirmation of reachability)
    Everything else refreshes reachability elsewhere but holds state here.
    """

    def make(to: State, trigger: str, reason: str) -> Optional[Transition]:
        return Transition(ctx.subject_id, ctx.state, to, trigger, reason, now)

    # --- Human override: always permitted, the sole route to Emergency. ---
    if event.event_type == EventType.OVERRIDE:
        target = event.target_state
        if target is None:
            return None
        return make(target, "override", f"Human override to {target.label}.")

    # Need Help / Emergency never change except by override (handled above).
    if ctx.state in _HUMAN_ONLY_EXIT:
        return None

    # --- Positive movement evidence resolves to OK. ---
    if event.event_type == EventType.POSITION and event.moving:
        if ctx.state != State.OK:
            return make(State.OK, "movement", "Movement observed.")
        return None  # already OK, just a refresh

    # --- Inbound message confirms reachability: Need Contact -> Delayed. ---
    if event.event_type == EventType.MESSAGE and ctx.state == State.NEED_CONTACT:
        return make(State.DELAYED, "message", "Message received.")

    return None


def evaluate_timers(ctx: SubjectContext, now: datetime) -> Optional[Transition]:
    """Return an absence-driven escalation, or ``None``.

    Absence escalation ladder (APRS primary source):
      OK      --(no position past absence window, and had prior movement)--> Delayed
      Delayed --(no position past extended window)-------------------------> Need Contact

    Absence never escalates past Need Contact, and never with no prior movement.
    """
    w = config.WINDOWS

    if ctx.state == State.OK:
        # Only escalate on absence if the subject was ever actually moving.
        if ctx.last_movement_at is None or ctx.last_position_at is None:
            return None
        gap = _elapsed(now, ctx.last_position_at)
        if gap is not None and gap >= config.scaled(w.aprs_absence):
            mins = int(w.aprs_absence // 60)
            return Transition(
                ctx.subject_id, State.OK, State.DELAYED, "absence",
                f"No position update for {mins} minutes.", now,
            )
        return None

    if ctx.state == State.DELAYED:
        # "No contact" means no signal of any kind — position *or* inbound message.
        # (A message that just recovered us from Need Contact must not be undone
        # by a stale position on the very next tick.)
        contacts = [t for t in (ctx.last_position_at, ctx.last_inbound_message_at)
                    if t is not None]
        if not contacts:
            return None
        gap = _elapsed(now, max(contacts))
        if gap is not None and gap >= config.scaled(w.aprs_extended):
            mins = int(w.aprs_extended // 60)
            return Transition(
                ctx.subject_id, State.DELAYED, State.NEED_CONTACT, "absence",
                f"No contact for {mins} minutes.", now,
            )
        return None

    # Need Contact: cooldown only, no further timer escalation.
    # Need Help / Emergency: no timers.
    return None


def next_context(ctx: SubjectContext, event: CanonicalEvent) -> SubjectContext:
    """Fold an event's observed timestamps into the context (reachability book-keeping).

    Pure helper used to keep an in-memory context current between DB reads; the
    authoritative context is always rebuilt from persisted facts.
    """
    updates: dict = {}
    ts = event.timestamp
    if event.source == Source.APRS:
        updates["last_aprs_at"] = ts
    if event.source == Source.MESH:
        updates["last_mesh_at"] = ts
    if event.event_type == EventType.POSITION:
        updates["last_position_at"] = ts
        if event.moving:
            updates["last_movement_at"] = ts
    if event.event_type == EventType.MESSAGE:
        updates["last_inbound_message_at"] = ts
    return replace(ctx, **updates)
