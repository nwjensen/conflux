"""Persistence: append-only facts + derived context.

State is never stored as a mutable field. Instead we persist an append-only log
of events, transitions, and transmissions, and *derive* current state and the
engine context from them. That keeps the system auditable and makes failover
recovery trivial: rebuild context from the log.

Works on SQLite (default, dev) and PostgreSQL (Compose / HA) unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from . import config
from .models import (
    CanonicalEvent,
    Channel,
    EventType,
    Source,
    State,
    TxStatus,
    utcnow,
)
from .state_engine import SubjectContext, Transition


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes across backends.

    SQLite drops tzinfo on write; this normalizes every value to aware-UTC on the
    way in and back out, so the rest of the system only ever sees aware UTC.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        # Use a timezone-aware column (Postgres TIMESTAMPTZ) so the absolute
        # instant round-trips correctly; naive TIMESTAMP would shift by the
        # session timezone. On SQLite this is still stored as an ISO string.
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    callsign: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    events: Mapped[list["Event"]] = relationship(back_populates="subject")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    source: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    subject: Mapped[Subject] = relationship(back_populates="events")


class StateTransition(Base):
    __tablename__ = "transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(16))
    to_state: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class Transmission(Base):
    __tablename__ = "transmissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default=TxStatus.SENT.value)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


# --- Engine / session wiring ---------------------------------------------------

def make_engine(url: Optional[str] = None):
    url = url or config.SETTINGS.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


_engine = None
_SessionLocal: Optional[sessionmaker] = None


def init_db(url: Optional[str] = None) -> None:
    """Create the engine + schema. Idempotent."""
    global _engine, _SessionLocal
    _engine = make_engine(url)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        raise RuntimeError("db not initialized; call init_db() first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --- Derivations: turn the append-only log into engine inputs -----------------

def current_state(session: Session, subject_id: int) -> tuple[State, datetime]:
    """Latest transition == current state. Absent any, the subject starts OK."""
    row = session.execute(
        select(StateTransition)
        .where(StateTransition.subject_id == subject_id)
        .order_by(StateTransition.at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        subj = session.get(Subject, subject_id)
        started = subj.created_at if subj else utcnow()
        return State.OK, started
    return State(row.to_state), row.at


def _last_ts(session: Session, subject_id: int, *, source: Optional[str] = None,
             event_type: Optional[str] = None, moving: Optional[bool] = None) -> Optional[datetime]:
    stmt = select(Event.timestamp).where(Event.subject_id == subject_id)
    if source is not None:
        stmt = stmt.where(Event.source == source)
    if event_type is not None:
        stmt = stmt.where(Event.event_type == event_type)
    stmt = stmt.order_by(Event.timestamp.desc())
    for (ts,) in session.execute(stmt).all():
        if moving is None:
            return ts
        # moving requires inspecting payload; walk rows until match.
        # (Handled by the dedicated query below for correctness.)
        return ts
    return None


def _last_moving_ts(session: Session, subject_id: int) -> Optional[datetime]:
    rows = session.execute(
        select(Event.timestamp, Event.payload)
        .where(Event.subject_id == subject_id, Event.event_type == EventType.POSITION.value)
        .order_by(Event.timestamp.desc())
        .limit(200)
    ).all()
    for ts, payload in rows:
        if payload and payload.get("moving"):
            return ts
    return None


def build_context(session: Session, subject_id: int) -> SubjectContext:
    """Rebuild the engine's :class:`SubjectContext` purely from stored facts."""
    state, entered = current_state(session, subject_id)
    last_escalation = session.execute(
        select(StateTransition.at)
        .where(StateTransition.subject_id == subject_id,
               StateTransition.trigger == "absence")
        .order_by(StateTransition.at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return SubjectContext(
        subject_id=subject_id,
        state=state,
        state_entered_at=entered,
        last_position_at=_last_ts(session, subject_id, event_type=EventType.POSITION.value),
        last_movement_at=_last_moving_ts(session, subject_id),
        last_aprs_at=_last_ts(session, subject_id, source=Source.APRS.value),
        last_mesh_at=_last_ts(session, subject_id, source=Source.MESH.value),
        last_inbound_message_at=_last_ts(session, subject_id, event_type=EventType.MESSAGE.value),
        last_escalation_at=last_escalation,
    )


# --- Writers ------------------------------------------------------------------

def record_event(session: Session, event: CanonicalEvent) -> Event:
    row = Event(
        subject_id=event.subject_id,
        timestamp=event.timestamp,
        source=event.source.value,
        event_type=event.event_type.value,
        confidence=event.confidence,
        payload=event.payload,
    )
    session.add(row)
    session.flush()
    return row


def record_transition(session: Session, t: Transition) -> StateTransition:
    row = StateTransition(
        subject_id=t.subject_id,
        from_state=t.from_state.value,
        to_state=t.to_state.value,
        trigger=t.trigger,
        reason=t.reason,
        at=t.at,
    )
    session.add(row)
    session.flush()
    return row


def record_transmission(
    session: Session,
    subject_id: int,
    channel: Channel,
    state: State,
    message: str,
    status: TxStatus,
    scheduled_for: Optional[datetime] = None,
    sent_at: Optional[datetime] = None,
) -> Transmission:
    row = Transmission(
        subject_id=subject_id,
        channel=channel.value,
        state=state.value,
        message=message,
        status=status.value,
        scheduled_for=scheduled_for,
        sent_at=sent_at,
    )
    session.add(row)
    session.flush()
    return row


def last_transmission(session: Session, subject_id: int, channel: Channel,
                      state: Optional[State] = None) -> Optional[Transmission]:
    """Most recent actually-sent transmission on a channel (optionally for one state)."""
    stmt = (
        select(Transmission)
        .where(Transmission.subject_id == subject_id,
               Transmission.channel == channel.value,
               Transmission.status.in_([TxStatus.SENT.value, TxStatus.CONFIRMED.value]))
    )
    if state is not None:
        stmt = stmt.where(Transmission.state == state.value)
    return session.execute(
        stmt.order_by(Transmission.created_at.desc()).limit(1)
    ).scalar_one_or_none()
