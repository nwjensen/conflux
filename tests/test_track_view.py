"""The map's read model: observed fixes only, oldest first, nothing inferred."""

from datetime import timedelta

from conflux import service, views
from conflux.models import CanonicalEvent, EventType, Source, utcnow


def _position(subject_id, *, at, lat, lon, moving=False, **payload):
    service.ingest(CanonicalEvent(
        subject_id=subject_id, timestamp=at, source=Source.APRS,
        event_type=EventType.POSITION,
        payload={"lat": lat, "lon": lon, "moving": moving, **payload},
    ), now=at)


def test_no_fixes_is_empty_not_an_error(subject):
    trk = views.track(subject)
    assert trk == {"subject_id": subject, "count": 0, "distinct_points": 0, "fixes": []}


def test_fixes_are_returned_oldest_first(subject):
    now = utcnow()
    for i in range(3):
        _position(subject, at=now - timedelta(minutes=10 - i), lat=39.0 + i, lon=-105.0)

    trk = views.track(subject)

    assert trk["count"] == 3
    assert [f["lat"] for f in trk["fixes"]] == [39.0, 40.0, 41.0]
    assert trk["fixes"][0]["at"] < trk["fixes"][-1]["at"]


def test_payload_details_are_carried_through(subject):
    now = utcnow()
    _position(subject, at=now, lat=39.64167, lon=-106.525, moving=True,
              speed_kmh=5.6, place="444.650MHz")

    fix = views.track(subject)["fixes"][0]

    assert fix["lat"] == 39.64167 and fix["lon"] == -106.525
    assert fix["moving"] is True
    assert fix["speed_kmh"] == 5.6
    assert fix["place"] == "444.650MHz"
    assert fix["source"] == "APRS"


def test_repeated_identical_fixes_report_one_distinct_point(subject):
    """The live subject beacons the same coordinates for hours; the UI must be
    able to say "many reports, one location" rather than imply movement."""
    now = utcnow()
    for i in range(5):
        _position(subject, at=now - timedelta(minutes=5 - i), lat=39.64167, lon=-106.525)

    trk = views.track(subject)

    assert trk["count"] == 5
    assert trk["distinct_points"] == 1


def test_positions_without_coordinates_are_skipped(subject):
    now = utcnow()
    service.ingest(CanonicalEvent(
        subject_id=subject, timestamp=now, source=Source.MESH,
        event_type=EventType.POSITION, payload={"moving": True},  # no lat/lon
    ), now=now)
    _position(subject, at=now, lat=39.0, lon=-105.0)

    assert views.track(subject)["count"] == 1


def test_non_position_events_are_excluded(subject):
    now = utcnow()
    service.ingest(CanonicalEvent(
        subject_id=subject, timestamp=now, source=Source.MESH,
        event_type=EventType.MESSAGE, payload={"text": "on my way"},
    ), now=now)

    assert views.track(subject)["count"] == 0


def test_limit_keeps_the_newest_fixes(subject):
    now = utcnow()
    for i in range(10):
        _position(subject, at=now - timedelta(minutes=10 - i), lat=39.0 + i, lon=-105.0)

    trk = views.track(subject, limit=3)

    assert trk["count"] == 3
    assert [f["lat"] for f in trk["fixes"]] == [46.0, 47.0, 48.0]
