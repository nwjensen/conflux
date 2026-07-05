"""Subject profile management: callsign validation, de-dup, create/update."""

import pytest

from conflux import service


# --- callsign normalization ---

def test_normalize_uppercases_and_trims():
    assert service.normalize_callsign("  ke0abc ") == "KE0ABC"
    assert service.normalize_callsign("ke0abc-9") == "KE0ABC-9"


def test_normalize_blank_is_none():
    assert service.normalize_callsign(None) is None
    assert service.normalize_callsign("   ") is None


def test_normalize_allows_alphanumeric_ssid():
    # Phone/APRS-IS beacons (e.g. APRS.fi) use alphanumeric SSIDs like -I.
    assert service.normalize_callsign("k0nwj-i") == "K0NWJ-I"


def test_alphanumeric_ssid_still_matches_on_base(fresh_db):
    from conflux.adapters import aprs
    sid = service.create_subject("Dad", "K0NWJ-I")
    callmap = aprs.build_callsign_map(service.subjects_public())
    assert callmap == {"K0NWJ": sid}
    # a beacon from any SSID of that base resolves to Dad, and the server-side
    # filter is a base wildcard that will actually catch it.
    assert aprs.resolve_subject("K0NWJ-I", callmap) == sid
    assert aprs.default_filter(callmap) == "b/K0NWJ*"


@pytest.mark.parametrize("bad", ["ABCDE", "12345", "KE0ABC-999", "K@0ABC", "KE0ABC-", "x"])
def test_normalize_rejects_malformed(bad):
    with pytest.raises(ValueError):
        service.normalize_callsign(bad)


# --- create ---

def test_create_requires_name(fresh_db):
    with pytest.raises(ValueError):
        service.create_subject("   ")


def test_create_stores_normalized_callsign(fresh_db):
    sid = service.create_subject("Dad", "ke0abc")
    rec = next(s for s in service.list_subjects() if s["id"] == sid)
    assert rec["callsign"] == "KE0ABC"
    assert rec["active"] is True


def test_create_rejects_duplicate_callsign(fresh_db):
    service.create_subject("Dad", "KE0ABC")
    # same base call, different SSID -> still a conflict
    with pytest.raises(ValueError, match="already assigned to Dad"):
        service.create_subject("Mom", "KE0ABC-7")


# --- update ---

def test_update_sets_callsign_for_aprs(fresh_db):
    sid = service.create_subject("Dad")            # no callsign yet
    out = service.update_subject(sid, "Dad", "KE0ABC", True)
    assert out["callsign"] == "KE0ABC"
    # and it shows up in the adapter's callsign map
    from conflux.adapters.aprs import build_callsign_map
    assert build_callsign_map(service.subjects_public()) == {"KE0ABC": sid}


def test_update_can_clear_callsign(fresh_db):
    sid = service.create_subject("Dad", "KE0ABC")
    out = service.update_subject(sid, "Dad", "", True)
    assert out["callsign"] is None


def test_update_rejects_callsign_taken_by_other(fresh_db):
    a = service.create_subject("Dad", "KE0ABC")
    b = service.create_subject("Mom", "KE0DEF")
    with pytest.raises(ValueError, match="already assigned to Dad"):
        service.update_subject(b, "Mom", "KE0ABC", True)
    # keeping its own callsign is fine (no self-conflict)
    assert service.update_subject(a, "Dad", "KE0ABC", True)["callsign"] == "KE0ABC"


def test_update_deactivate_hides_from_active_list(fresh_db):
    sid = service.create_subject("Teen", "KE0GHI")
    service.update_subject(sid, "Teen", "KE0GHI", False)
    assert all(s["id"] != sid for s in service.list_subjects())          # active-only
    assert any(s["id"] == sid for s in service.list_subjects(include_inactive=True))


def test_update_missing_subject_raises(fresh_db):
    with pytest.raises(ValueError, match="not found"):
        service.update_subject(999, "Ghost", None, True)
