"""Service layer: the only place engine, persistence, and orchestrator meet.

Two operations drive everything:
  * :func:`ingest`      — an observation arrives -> maybe a transition -> fan-out
  * :func:`tick_subject`— periodic evaluation -> absence escalation + SMS flush

Both are synchronous and transactional (SQLite/Postgres safe). The async loops in
``main`` simply call these on a cadence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, db, orchestrator, state_engine
from .db import Subject, Transmission
from .models import CanonicalEvent, Channel, EventType, Source, State, TxStatus, utcnow
from .state_engine import Transition


def apply_transition(session: Session, t: Transition, now: datetime) -> None:
    """Persist a state change and fan it out. No-op if it isn't a real change."""
    if not t.is_change:
        return
    db.record_transition(session, t)
    orchestrator.on_state_change(session, t.subject_id, t.to_state, now)


def ingest(event: CanonicalEvent, now: Optional[datetime] = None) -> Optional[Transition]:
    """Process one observation. Returns the transition it caused, if any."""
    now = now or utcnow()
    with db.session_scope() as session:
        db.record_event(session, event)

        # Delivery reports update the matching transmission; they never change state.
        if event.event_type == EventType.DELIVERY:
            _apply_delivery(session, event)
            return None

        ctx = db.build_context(session, event.subject_id)
        transition = state_engine.apply_event(ctx, event, now)
        if transition is not None and transition.is_change:
            apply_transition(session, transition, now)
            return transition
        return None


def tick_subject(subject_id: int, now: Optional[datetime] = None) -> Optional[Transition]:
    """Evaluate absence timers and flush any due scheduled SMS for one subject."""
    now = now or utcnow()
    with db.session_scope() as session:
        ctx = db.build_context(session, subject_id)
        transition = state_engine.evaluate_timers(ctx, now)
        result = None
        if transition is not None and transition.is_change:
            apply_transition(session, transition, now)
            result = transition
        orchestrator.flush_scheduled_sms(session, subject_id, now)
        return result


def tick_all(now: Optional[datetime] = None) -> list[Transition]:
    now = now or utcnow()
    transitions: list[Transition] = []
    for sid in active_subject_ids():
        t = tick_subject(sid, now)
        if t is not None:
            transitions.append(t)
    return transitions


def _apply_delivery(session: Session, event: CanonicalEvent) -> None:
    """Confirm/fail the most recent SMS send for the subject."""
    confirmed = str(event.payload.get("status", "confirmed")).lower() != "failed"
    row = session.execute(
        select(Transmission)
        .where(Transmission.subject_id == event.subject_id,
               Transmission.channel == Channel.SMS.value,
               Transmission.status == TxStatus.SENT.value)
        .order_by(Transmission.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is not None:
        row.status = TxStatus.CONFIRMED.value if confirmed else TxStatus.FAILED.value
        session.flush()


# --- Subject registry ---------------------------------------------------------

def active_subject_ids() -> list[int]:
    with db.session_scope() as session:
        return list(session.execute(
            select(Subject.id).where(Subject.active.is_(True)).order_by(Subject.id)
        ).scalars().all())


def ensure_seed_subjects() -> None:
    """Seed subjects from config on first start (idempotent)."""
    with db.session_scope() as session:
        existing = session.execute(select(Subject.id).limit(1)).first()
        if existing is not None:
            return
        for spec in config.SETTINGS.seed_subjects.split(","):
            spec = spec.strip()
            if not spec:
                continue
            name, _, callsign = spec.partition(":")
            session.add(Subject(name=name.strip(), callsign=(callsign.strip() or None)))


def override(subject_id: int, target: State, immediate: bool = False,
             now: Optional[datetime] = None) -> Optional[Transition]:
    """Operator override: set state directly (the only path into Emergency).

    When ``immediate`` is set, also push an out-of-schedule SMS snapshot.
    """
    now = now or utcnow()
    event = CanonicalEvent(
        subject_id=subject_id,
        source=Source.HUMAN,
        event_type=EventType.OVERRIDE,
        payload={"state": target.value},
    )
    transition = ingest(event, now=now)
    # Emergency already fans out an immediate SMS; only force a send for the
    # non-emergency states, where SMS would otherwise wait for a scheduled window.
    if immediate and target != State.EMERGENCY:
        with db.session_scope() as session:
            state, _ = db.current_state(session, subject_id)
            orchestrator.send_sms_now(session, subject_id, state, now)
    return transition


def create_subject(name: str, callsign: Optional[str] = None) -> int:
    with db.session_scope() as session:
        subj = Subject(name=name, callsign=callsign)
        session.add(subj)
        session.flush()
        return subj.id
