"""Orchestration: deterministic mapping of state to outbound channels.

Fan-out policy (Technical Spec §4):
  * APRS / Mesh  : immediate on state change (guarded by a per-channel cooldown)
  * SMS          : clock-gated to :00 / :30; Emergency bypasses the schedule
  * CW           : optional, symbolic (opt-in)
  * Voice        : manual only, never automatic
  * Hub          : always current (the UI reads state directly; no transmission row)

Rules: duplicate sends are suppressed unless state changes; Emergency and human
override bypass scheduling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, db, timers
from .message_catalog import render
from .models import Channel, State, TxStatus
from .db import Transmission


_IMMEDIATE_COOLDOWN = {
    Channel.APRS: config.WINDOWS.aprs_cooldown,
    Channel.MESH: config.WINDOWS.mesh_cooldown,
}


def on_state_change(session: Session, subject_id: int, state: State, now: datetime) -> list[Transmission]:
    """Fan a confirmed state change out across channels. Returns rows created."""
    created: list[Transmission] = []

    # --- Immediate RF channels (APRS, Mesh), with cooldown de-duplication. ---
    for channel in (Channel.APRS, Channel.MESH):
        created.extend(_send_immediate(session, subject_id, channel, state, now))

    # --- CW (optional, symbolic). ---
    if config.SETTINGS.cw_enabled:
        created.append(
            db.record_transmission(session, subject_id, Channel.CW, state,
                                   render(state, Channel.CW), TxStatus.SENT, sent_at=now)
        )

    # --- SMS: Emergency bypasses the schedule; otherwise queue for next window. ---
    if state == State.EMERGENCY:
        created.append(send_sms_now(session, subject_id, state, now))
    else:
        created.append(_queue_sms(session, subject_id, state, now))

    return created


def _send_immediate(session: Session, subject_id: int, channel: Channel,
                    state: State, now: datetime) -> list[Transmission]:
    cooldown = _IMMEDIATE_COOLDOWN[channel]
    last = db.last_transmission(session, subject_id, channel, state=state)
    # Suppress only if this same state was already sent inside the cooldown window.
    if (last is not None
            and timers.within_cooldown(last.sent_at or last.created_at, cooldown, now)):
        return [db.record_transmission(session, subject_id, channel, state,
                                       render(state, channel), TxStatus.SUPPRESSED)]
    return [db.record_transmission(session, subject_id, channel, state,
                                   render(state, channel), TxStatus.SENT, sent_at=now)]


def _pending_sms(session: Session, subject_id: int) -> Optional[Transmission]:
    return session.execute(
        select(Transmission)
        .where(Transmission.subject_id == subject_id,
               Transmission.channel == Channel.SMS.value,
               Transmission.status == TxStatus.PENDING.value)
        .order_by(Transmission.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _queue_sms(session: Session, subject_id: int, state: State, now: datetime) -> Transmission:
    """Queue (or re-point) a single pending SMS for the next scheduled window."""
    pending = _pending_sms(session, subject_id)
    window = timers.next_sms_window(now, last_flush=None)
    if pending is not None:
        # Keep at most one pending SMS; update it to the latest state.
        pending.state = state.value
        pending.message = render(state, Channel.SMS)
        pending.scheduled_for = window
        session.flush()
        return pending
    return db.record_transmission(session, subject_id, Channel.SMS, state,
                                  render(state, Channel.SMS), TxStatus.PENDING,
                                  scheduled_for=window)


def send_sms_now(session: Session, subject_id: int, state: State, now: datetime) -> Transmission:
    # Emergency bypass: drop any pending, send immediately.
    pending = _pending_sms(session, subject_id)
    if pending is not None:
        pending.status = TxStatus.SUPPRESSED.value
        session.flush()
    return db.record_transmission(session, subject_id, Channel.SMS, state,
                                  render(state, Channel.SMS), TxStatus.SENT, sent_at=now)


def flush_scheduled_sms(session: Session, subject_id: int, now: datetime) -> Optional[Transmission]:
    """If a scheduled SMS window has opened, send a snapshot of current state.

    Suppresses the send if the current state's SMS equals the last one actually
    sent (duplicate suppression unless state changed).
    """
    pending = _pending_sms(session, subject_id)
    if pending is None or pending.scheduled_for is None or pending.scheduled_for > now:
        return None

    state, _ = db.current_state(session, subject_id)  # snapshot current state
    last_sent = db.last_transmission(session, subject_id, Channel.SMS)

    if last_sent is not None and last_sent.state == state.value:
        pending.status = TxStatus.SUPPRESSED.value
        session.flush()
        return None

    pending.state = state.value
    pending.message = render(state, Channel.SMS)
    pending.status = TxStatus.SENT.value
    pending.sent_at = now
    session.flush()
    return pending
