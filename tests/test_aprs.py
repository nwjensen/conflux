"""APRS adapter transforms — pure, offline (no network, no live APRS-IS)."""

import aprslib
import pytest

from conflux.adapters import aprs
from conflux.models import EventType, Source


# --- callsign handling ---

def test_base_callsign_strips_ssid():
    assert aprs.base_callsign("KE0ABC-9") == "KE0ABC"
    assert aprs.base_callsign("ke0abc") == "KE0ABC"


def test_callsign_map_and_resolution():
    subs = [{"id": 1, "name": "Dad", "callsign": "KE0ABC"},
            {"id": 2, "name": "Mom", "callsign": "KE0DEF"},
            {"id": 3, "name": "Kid", "callsign": None}]
    cm = aprs.build_callsign_map(subs)
    assert cm == {"KE0ABC": 1, "KE0DEF": 2}
    assert aprs.resolve_subject("KE0ABC-9", cm) == 1   # SSID ignored
    assert aprs.resolve_subject("KE0DEF", cm) == 2
    assert aprs.resolve_subject("W1AW-1", cm) is None   # unknown sender


def test_default_filter_from_callsigns():
    cm = {"KE0DEF": 2, "KE0ABC": 1}
    assert aprs.default_filter(cm) == "b/KE0ABC*/KE0DEF*"
    assert aprs.default_filter({}) == "t/p"


# --- movement detection ---

def test_is_moving_by_speed():
    cur = (41.25, -95.93)
    assert aprs.is_moving(22.2, None, cur, 3.0, 50.0) is True    # fast
    assert aprs.is_moving(0.0, None, cur, 3.0, 50.0) is False    # stopped, no prior fix


def test_is_moving_by_distance_when_no_speed():
    prev = (41.2500, -95.9300)
    near = (41.25005, -95.93005)   # a few metres
    far = (41.2600, -95.9300)      # ~1.1 km north
    assert aprs.is_moving(None, prev, near, 3.0, 50.0) is False
    assert aprs.is_moving(None, prev, far, 3.0, 50.0) is True


def test_haversine_known_distance():
    # 0.01 deg latitude ~ 1.11 km
    d = aprs.haversine_m(41.25, -95.93, 41.26, -95.93)
    assert 1100 < d < 1120


# --- packet -> canonical event ---

def test_packet_to_event_position():
    packet = aprslib.parse("KE0ABC-9>APRS,TCPIP*:!4115.30N/09556.07W>088/012 en route")
    ev = aprs.packet_to_event(packet, subject_id=1, moving=True)
    assert ev is not None
    assert ev.source == Source.APRS and ev.event_type == EventType.POSITION
    assert ev.subject_id == 1
    assert ev.payload["moving"] is True
    assert ev.payload["place"] == "en route"
    assert abs(ev.payload["lat"] - 41.255) < 0.01
    assert "speed_kmh" in ev.payload


def test_packet_to_event_skips_non_position():
    # A status/message frame has no lat/lon -> no event.
    packet = aprslib.parse("KE0ABC>APRS,TCPIP*::KE0DEF   :hello")
    assert aprs.packet_to_event(packet, subject_id=1, moving=False) is None


def test_full_transform_pipeline():
    # Simulate what _on_packet does, without any network.
    callmap = {"KE0ABC": 7}
    packet = aprslib.parse("KE0ABC-5>APRS,TCPIP*:!4115.30N/09556.07W>088/000 stopped")
    sid = aprs.resolve_subject(packet["from"], callmap)
    assert sid == 7
    moving = aprs.is_moving(packet.get("speed"), None, (packet["latitude"], packet["longitude"]), 3.0, 50.0)
    ev = aprs.packet_to_event(packet, sid, moving)
    assert ev.subject_id == 7 and ev.payload["moving"] is False
