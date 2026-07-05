"""The message catalog is complete and renders on every transport."""

import pytest

from conflux.message_catalog import CATALOG, render
from conflux.models import Channel, State


@pytest.mark.parametrize("state", list(State))
def test_every_state_has_an_entry(state):
    assert state in CATALOG


@pytest.mark.parametrize("state", list(State))
@pytest.mark.parametrize("channel", [Channel.APRS, Channel.MESH, Channel.SMS,
                                     Channel.CW, Channel.HUB, Channel.VOICE])
def test_render_is_nonempty_for_all(state, channel):
    assert render(state, channel).strip()


def test_cw_symbols_match_spec():
    assert render(State.OK, Channel.CW) == "K"
    assert render(State.DELAYED, Channel.CW) == "D"
    assert render(State.NEED_CONTACT, Channel.CW) == "R"
    assert render(State.NEED_HELP, Channel.CW) == "H"
    assert render(State.EMERGENCY, Channel.CW) == "SOS"


def test_emergency_is_only_urgent_string():
    # Non-emergency SMS must not shout; emergency must.
    assert render(State.OK, Channel.SMS) == "OK. Moving normally."
    assert "EMERGENCY" in render(State.EMERGENCY, Channel.SMS)
