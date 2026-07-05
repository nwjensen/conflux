"""Integration tests: ingest -> state -> orchestration, through a real DB."""

from datetime import timedelta

from conflux import config, db, service, timers
from conflux.models import (
    CanonicalEvent,
    Channel,
    EventType,
    Source,
    State,
    TxStatus,
    utcnow,
)
from conflux.orchestrator import flush_scheduled_sms


def position(subject_id, at, moving=True):
    return CanonicalEvent(subject_id=subject_id, timestamp=at, source=Source.APRS,
                          event_type=EventType.POSITION, payload={"moving": moving})


def _state(subject_id):
    with db.session_scope() as s:
        st, _ = db.current_state(s, subject_id)
        return st


def _txns(subject_id, channel=None, status=None):
    with db.session_scope() as s:
        rows = db.Transmission.__table__
        from sqlalchemy import select
        stmt = select(db.Transmission).where(db.Transmission.subject_id == subject_id)
        if channel:
            stmt = stmt.where(db.Transmission.channel == channel.value)
        if status:
            stmt = stmt.where(db.Transmission.status == status.value)
        return list(s.execute(stmt).scalars().all())


def test_position_keeps_ok(subject):
    now = utcnow()
    service.ingest(position(subject, now), now=now)
    assert _state(subject) == State.OK


def test_absence_escalates_ok_to_delayed_to_need_contact(subject):
    t0 = utcnow()
    service.ingest(position(subject, t0), now=t0)
    assert _state(subject) == State.OK

    # Past the APRS absence window -> Delayed.
    t1 = t0 + timedelta(seconds=config.WINDOWS.aprs_absence + 5)
    service.tick_subject(subject, now=t1)
    assert _state(subject) == State.DELAYED

    # Past the extended window -> Need Contact.
    t2 = t0 + timedelta(seconds=config.WINDOWS.aprs_extended + 5)
    service.tick_subject(subject, now=t2)
    assert _state(subject) == State.NEED_CONTACT

    # Absence never goes past Need Contact.
    t3 = t0 + timedelta(hours=8)
    service.tick_subject(subject, now=t3)
    assert _state(subject) == State.NEED_CONTACT


def test_inbound_message_recovers_from_need_contact(subject):
    t0 = utcnow()
    service.ingest(position(subject, t0), now=t0)
    # The ladder advances one rung per tick, as the real tick loop does.
    service.tick_subject(subject, now=t0 + timedelta(seconds=config.WINDOWS.aprs_absence + 5))
    service.tick_subject(subject, now=t0 + timedelta(seconds=config.WINDOWS.aprs_extended + 5))
    assert _state(subject) == State.NEED_CONTACT

    t_msg = t0 + timedelta(seconds=config.WINDOWS.aprs_extended + 60)
    msg = CanonicalEvent(subject_id=subject, timestamp=t_msg, source=Source.MESH,
                         event_type=EventType.MESSAGE, payload={"text": "OK. Moving normally."})
    service.ingest(msg, now=t_msg)
    assert _state(subject) == State.DELAYED

    # The recovery must not be undone by the very next tick (stale position).
    service.tick_subject(subject, now=t_msg + timedelta(seconds=5))
    assert _state(subject) == State.DELAYED

    # But a fresh extended window of silence *after* the message re-escalates.
    service.tick_subject(subject, now=t_msg + timedelta(seconds=config.WINDOWS.aprs_extended + 5))
    assert _state(subject) == State.NEED_CONTACT


def test_state_change_fans_out_to_aprs_and_mesh(subject):
    service.override(subject, State.DELAYED)
    aprs = _txns(subject, Channel.APRS, TxStatus.SENT)
    mesh = _txns(subject, Channel.MESH, TxStatus.SENT)
    assert len(aprs) == 1 and aprs[0].message == "Delayed. Safe."
    assert len(mesh) == 1 and mesh[0].message == "Delayed. Safe."


def test_non_emergency_sms_is_queued_then_flushed(subject):
    service.override(subject, State.DELAYED)
    pending = _txns(subject, Channel.SMS, TxStatus.PENDING)
    assert len(pending) == 1
    window = pending[0].scheduled_for

    # Before the window: nothing sent.
    with db.session_scope() as s:
        assert flush_scheduled_sms(s, subject, window - timedelta(seconds=1)) is None
    # At/after the window: snapshot SMS is sent.
    with db.session_scope() as s:
        sent = flush_scheduled_sms(s, subject, window + timedelta(seconds=1))
        assert sent is not None and sent.message == "Delayed. Safe."


def test_emergency_bypasses_sms_schedule(subject):
    service.override(subject, State.EMERGENCY)
    sent = _txns(subject, Channel.SMS, TxStatus.SENT)
    pending = _txns(subject, Channel.SMS, TxStatus.PENDING)
    assert len(sent) == 1 and "EMERGENCY" in sent[0].message
    assert len(pending) == 0


def test_repeated_same_state_does_not_resend(subject):
    # Re-asserting the same state is not a change -> no second fan-out.
    service.override(subject, State.DELAYED)
    service.override(subject, State.DELAYED)  # no-op
    aprs_sent = _txns(subject, Channel.APRS, TxStatus.SENT)
    assert len(aprs_sent) == 1  # duplicate suppressed by "only send on change"


def test_flapping_back_within_cooldown_is_suppressed(subject):
    # OK -> DELAYED -> OK -> DELAYED, all within cooldown. The final DELAYED send
    # lands within the cooldown of the earlier DELAYED send -> suppressed.
    now = utcnow()
    service.override(subject, State.DELAYED, now=now)
    service.override(subject, State.OK, now=now + timedelta(seconds=1))
    service.override(subject, State.DELAYED, now=now + timedelta(seconds=2))
    suppressed = _txns(subject, Channel.APRS, TxStatus.SUPPRESSED)
    assert len(suppressed) >= 1


def test_restart_recovers_state_from_log(subject):
    # State is derived, not stored: re-deriving after a fresh context yields the same state.
    service.override(subject, State.NEED_HELP)
    assert _state(subject) == State.NEED_HELP
    with db.session_scope() as s:
        ctx = db.build_context(s, subject)
    assert ctx.state == State.NEED_HELP  # rebuilt purely from the transition log
