"""Service layer: the only place engine, persistence, and orchestrator meet.

Two operations drive everything:
  * :func:`ingest`      — an observation arrives -> maybe a transition -> fan-out
  * :func:`tick_subject`— periodic evaluation -> absence escalation + SMS flush

Both are synchronous and transactional (SQLite/Postgres safe). The async loops in
``main`` simply call these on a cadence.
"""

from __future__ import annotations

import re
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

# A base amateur callsign (SSID stripped) plus an optional SSID. Traditional
# AX.25 SSIDs are numeric (-1..-15), but app/APRS-IS-originated beacons (e.g. a
# phone via APRS.fi) commonly use an alphanumeric SSID like ``-I`` — so allow
# either. We match beacons on the base, so the SSID is cosmetic but preserved.
_CALLSIGN_RE = re.compile(r"^[A-Z0-9]{2,7}(-[A-Z0-9]{1,2})?$")


def _base(call: str) -> str:
    """Strip the SSID and uppercase: ``ke0abc-9`` -> ``KE0ABC``."""
    return call.split("-", 1)[0].strip().upper()


def normalize_callsign(raw: Optional[str]) -> Optional[str]:
    """Validate + normalize a callsign, or return ``None`` for blank input.

    Raises :class:`ValueError` with a human message when the value is malformed —
    the API turns that into a 400 the editor can show inline.
    """
    if raw is None:
        return None
    cs = raw.strip().upper()
    if not cs:
        return None
    base = _base(cs)
    if (not _CALLSIGN_RE.match(cs)
            or not any(c.isdigit() for c in base)
            or not any(c.isalpha() for c in base)):
        raise ValueError(f"“{raw}” is not a valid callsign (e.g. KE0ABC or KE0ABC-9).")
    return cs


def _callsign_conflict(session: Session, base: str, exclude_id: Optional[int]) -> Optional[str]:
    """Return the name of another subject already using this base callsign, if any."""
    rows = session.execute(select(Subject.id, Subject.name, Subject.callsign)).all()
    for sid, name, cs in rows:
        if sid == exclude_id or not cs:
            continue
        if _base(cs) == base:
            return name
    return None


def _maybe_refresh_aprs() -> None:
    """Nudge the running APRS-IS adapter to reconnect with the new roster.

    No-op when APRS is disabled or the adapter isn't running (e.g. under tests).
    A callsign change alters the server-side filter, so a reconnect is required
    for new beacons to actually arrive.
    """
    if not config.SETTINGS.aprs_enabled:
        return
    try:
        from . import app_state  # late import: app_state imports service
        app_state.refresh_aprs()
    except Exception:  # noqa: BLE001 — a refresh failure must not fail the edit
        pass


def active_subject_ids() -> list[int]:
    with db.session_scope() as session:
        return list(session.execute(
            select(Subject.id).where(Subject.active.is_(True)).order_by(Subject.id)
        ).scalars().all())


def subjects_public() -> list[dict]:
    """Minimal subject records (id/name/callsign) for adapters and registries."""
    with db.session_scope() as session:
        rows = session.execute(
            select(Subject.id, Subject.name, Subject.callsign)
            .where(Subject.active.is_(True)).order_by(Subject.id)
        ).all()
        return [{"id": r.id, "name": r.name, "callsign": r.callsign} for r in rows]


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


def list_subjects(include_inactive: bool = False) -> list[dict]:
    """Full editable records (id/name/callsign/active) for the manage UI."""
    with db.session_scope() as session:
        stmt = select(Subject).order_by(Subject.id)
        if not include_inactive:
            stmt = stmt.where(Subject.active.is_(True))
        return [
            {"id": s.id, "name": s.name, "callsign": s.callsign, "active": s.active}
            for s in session.execute(stmt).scalars().all()
        ]


def create_subject(name: str, callsign: Optional[str] = None, active: bool = True) -> int:
    """Add a subject. Validates the callsign and rejects duplicates. Returns the id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")
    cs = normalize_callsign(callsign)
    with db.session_scope() as session:
        if cs is not None:
            other = _callsign_conflict(session, _base(cs), None)
            if other is not None:
                raise ValueError(f"Callsign {cs} is already assigned to {other}.")
        subj = Subject(name=name, callsign=cs, active=active)
        session.add(subj)
        session.flush()
        new_id = subj.id
    _maybe_refresh_aprs()
    return new_id


def update_subject(subject_id: int, name: str, callsign: Optional[str], active: bool) -> dict:
    """Edit a subject's profile. Validates + de-dups the callsign; refreshes APRS.

    Raises :class:`ValueError` (→ 400) when the subject is missing, the name is
    blank, the callsign is malformed, or the callsign collides with another subject.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")
    cs = normalize_callsign(callsign)
    with db.session_scope() as session:
        subj = session.get(Subject, subject_id)
        if subj is None:
            raise ValueError("Subject not found.")
        if cs is not None:
            other = _callsign_conflict(session, _base(cs), subject_id)
            if other is not None:
                raise ValueError(f"Callsign {cs} is already assigned to {other}.")
        subj.name = name
        subj.callsign = cs
        subj.active = bool(active)
        session.flush()
        result = {"id": subj.id, "name": subj.name,
                  "callsign": subj.callsign, "active": subj.active}
    _maybe_refresh_aprs()
    return result
