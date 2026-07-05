"""aprs.fi poller transforms — pure, offline (no network, no aprs.fi calls)."""

from datetime import timezone

from conflux.adapters import aprs, aprsfi
from conflux.models import EventType, Source


SAMPLE = {
    "name": "K0NWJ-I", "time": "1751749564", "lasttime": "1751749564",
    "lat": "41.22983", "lng": "-96.26150", "speed": "0", "course": "147",
    "comment": "Elkhorn NE", "symbol": "/$",
}


# --- response parsing ---

def test_parse_entries_ok():
    data = {"result": "ok", "found": 1, "entries": [SAMPLE]}
    assert aprsfi.parse_entries(data) == [SAMPLE]


def test_parse_entries_error_or_empty():
    assert aprsfi.parse_entries({"result": "fail", "description": "auth failed"}) == []
    assert aprsfi.parse_entries({"result": "ok"}) == []
    assert aprsfi.parse_entries("nonsense") == []


# --- entry -> canonical event ---

def test_entry_to_event_uses_lasttime_as_timestamp():
    ev = aprsfi.entry_to_event(SAMPLE, subject_id=1, moving=False)
    assert ev is not None
    assert ev.source == Source.APRS and ev.event_type == EventType.POSITION
    assert ev.subject_id == 1
    # timestamp is the real last-heard time, not "now"
    assert ev.timestamp.tzinfo is timezone.utc
    assert int(ev.timestamp.timestamp()) == 1751749564
    assert abs(ev.payload["lat"] - 41.22983) < 1e-4
    assert ev.payload["place"] == "Elkhorn NE"
    assert ev.payload["moving"] is False
    assert ev.payload["speed_kmh"] == 0.0


def test_entry_to_event_skips_without_position():
    assert aprsfi.entry_to_event({"name": "K0NWJ-I", "lasttime": "1"}, 1, False) is None
    assert aprsfi.entry_to_event({"lat": "41.2", "lng": "-96.2"}, 1, False) is None  # no time


def test_entry_epoch():
    assert aprsfi.entry_epoch(SAMPLE) == 1751749564
    assert aprsfi.entry_epoch({"time": "42"}) == 42
    assert aprsfi.entry_epoch({}) is None


def test_is_stale_guards_ancient_cached_fixes():
    now = 1_000_000.0
    fresh = int(now - 3600)          # 1 hour old
    ancient = int(now - 30 * 86400)  # 30 days old
    assert aprsfi.is_stale(fresh, now, 24.0) is False
    assert aprsfi.is_stale(ancient, now, 24.0) is True
    assert aprsfi.is_stale(ancient, now, 0) is False   # guard disabled
    assert aprsfi.is_stale(None, now, 24.0) is False


# --- full transform pipeline (parse -> resolve -> movement -> event) ---

def test_full_transform_pipeline():
    callmap = aprs.build_callsign_map([{"id": 5, "name": "Dad", "callsign": "K0NWJ-I"}])
    entries = aprsfi.parse_entries({"result": "ok", "entries": [SAMPLE]})
    entry = entries[0]
    sid = aprs.resolve_subject(entry["name"], callmap)      # base-call match ignores SSID
    assert sid == 5
    moving = aprs.is_moving(float(entry["speed"]), None,
                            (float(entry["lat"]), float(entry["lng"])), 3.0, 50.0)
    ev = aprsfi.entry_to_event(entry, sid, moving)
    assert ev.subject_id == 5 and ev.payload["moving"] is False
