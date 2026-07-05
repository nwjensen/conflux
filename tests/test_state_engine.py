"""Pure state-engine tests — the transition table, exhaustively and without I/O."""

from datetime import timedelta

import pytest

from conflux import config
from conflux.models import CanonicalEvent, EventType, Source, State, utcnow
from conflux.state_engine import SubjectContext, apply_event, evaluate_timers

T0 = utcnow()


def ctx(state, **kw):
    return SubjectContext(subject_id=1, state=state, state_entered_at=T0, **kw)


def override_event(target):
    return CanonicalEvent(subject_id=1, source=Source.HUMAN,
                          event_type=EventType.OVERRIDE, payload={"state": target.value})


def position_event(moving=True):
    return CanonicalEvent(subject_id=1, source=Source.APRS,
                          event_type=EventType.POSITION, payload={"moving": moving})


def message_event():
    return CanonicalEvent(subject_id=1, source=Source.MESH,
                          event_type=EventType.MESSAGE, payload={"text": "OK. Moving normally."})


# --- Override: the only path into Emergency, always permitted ---

@pytest.mark.parametrize("start", list(State))
@pytest.mark.parametrize("target", list(State))
def test_override_reaches_any_state(start, target):
    t = apply_event(ctx(start), override_event(target), T0)
    if start == target:
        assert t is None or not t.is_change
    else:
        assert t is not None and t.to_state == target and t.trigger == "override"


def test_emergency_only_via_override():
    # No non-override event may produce Emergency.
    for ev in (position_event(), message_event(), position_event(moving=False)):
        for start in (State.OK, State.DELAYED, State.NEED_CONTACT):
            t = apply_event(ctx(start), ev, T0)
            assert t is None or t.to_state != State.EMERGENCY


# --- Movement evidence resolves to OK (except from human-only-exit states) ---

@pytest.mark.parametrize("start", [State.DELAYED, State.NEED_CONTACT])
def test_movement_resolves_to_ok(start):
    t = apply_event(ctx(start), position_event(moving=True), T0)
    assert t is not None and t.to_state == State.OK and t.trigger == "movement"


def test_movement_while_ok_is_noop():
    assert apply_event(ctx(State.OK), position_event(moving=True), T0) is None


@pytest.mark.parametrize("start", [State.NEED_HELP, State.EMERGENCY])
def test_no_auto_downgrade_from_help_or_emergency(start):
    # Neither movement nor inbound messages may exit these automatically.
    assert apply_event(ctx(start), position_event(moving=True), T0) is None
    assert apply_event(ctx(start), message_event(), T0) is None
    # Only override works.
    t = apply_event(ctx(start), override_event(State.OK), T0)
    assert t is not None and t.to_state == State.OK


# --- Inbound message confirms reachability: Need Contact -> Delayed ---

def test_message_downgrades_need_contact():
    t = apply_event(ctx(State.NEED_CONTACT), message_event(), T0)
    assert t is not None and t.to_state == State.DELAYED and t.trigger == "message"


def test_message_while_ok_is_noop():
    assert apply_event(ctx(State.OK), message_event(), T0) is None


# --- Absence ladder (timers) ---

def test_absence_ok_to_delayed_requires_prior_movement():
    moved = T0
    now = T0 + timedelta(seconds=config.WINDOWS.aprs_absence + 1)
    c = ctx(State.OK, last_position_at=moved, last_movement_at=moved)
    t = evaluate_timers(c, now)
    assert t is not None and t.to_state == State.DELAYED and t.trigger == "absence"


def test_absence_without_prior_movement_does_not_escalate():
    now = T0 + timedelta(seconds=config.WINDOWS.aprs_absence + 1)
    c = ctx(State.OK, last_position_at=T0, last_movement_at=None)
    assert evaluate_timers(c, now) is None


def test_absence_within_window_is_noop():
    now = T0 + timedelta(seconds=config.WINDOWS.aprs_absence - 5)
    c = ctx(State.OK, last_position_at=T0, last_movement_at=T0)
    assert evaluate_timers(c, now) is None


def test_delayed_to_need_contact_after_extended_window():
    now = T0 + timedelta(seconds=config.WINDOWS.aprs_extended + 1)
    c = ctx(State.DELAYED, last_position_at=T0, last_movement_at=T0)
    t = evaluate_timers(c, now)
    assert t is not None and t.to_state == State.NEED_CONTACT


def test_absence_never_escalates_past_need_contact():
    now = T0 + timedelta(hours=6)
    c = ctx(State.NEED_CONTACT, last_position_at=T0, last_movement_at=T0)
    assert evaluate_timers(c, now) is None
