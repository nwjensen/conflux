"""aprs.fi poller — position input via the aprs.fi HTTP API.

A *pull* alternative to the APRS-IS adapter. Some positions live only in
aprs.fi (e.g. its browser "share location" / web-station feature) and are never
transmitted onto APRS-IS, so an APRS-IS subscriber can't see them. This adapter
polls the aprs.fi API for each subject's callsign and feeds the same canonical
position events as any other input. The core never learns aprs.fi exists.

Correctness note: aprs.fi returns the *last known* position every poll, so we
key on the entry's ``lasttime`` (when the target was actually last heard) — both
as the event timestamp and to de-duplicate. A stale fix is therefore never
re-emitted, and the absence timers escalate on real silence, not on polling.

The callsign->subject mapping and movement detection are shared with the APRS-IS
adapter (:mod:`conflux.adapters.aprs`) — only the transport differs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .. import config, service
from ..models import CanonicalEvent, EventType, Source, utcnow
from .aprs import build_callsign_map, is_moving, resolve_subject
from .base import Adapter, EmitFn

log = logging.getLogger("conflux.aprsfi")

_USER_AGENT = "Conflux/1.0 (+https://github.com/nwjensen/conflux)"


# --- Pure transforms (no network, unit-tested) --------------------------------

def parse_entries(data: dict) -> list[dict]:
    """Pull the location entries out of an aprs.fi API response.

    Returns ``[]`` for an error response or a response with no entries; the
    caller logs the ``description`` on failure.
    """
    if not isinstance(data, dict) or data.get("result") != "ok":
        return []
    entries = data.get("entries")
    return entries if isinstance(entries, list) else []


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def entry_to_event(entry: dict, subject_id: int, moving: bool) -> Optional[CanonicalEvent]:
    """Build a canonical position event from one aprs.fi ``loc`` entry.

    Returns ``None`` when the entry lacks a usable lat/lon/time.
    """
    lat, lon = _to_float(entry.get("lat")), _to_float(entry.get("lng"))
    lasttime = entry.get("lasttime") or entry.get("time")
    if lat is None or lon is None or lasttime is None:
        return None
    try:
        ts = datetime.fromtimestamp(int(lasttime), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    payload = {"lat": round(lat, 5), "lon": round(lon, 5), "moving": moving}
    comment = entry.get("comment")
    if comment:
        payload["place"] = str(comment)[:60]
    speed = _to_float(entry.get("speed"))
    if speed is not None:
        payload["speed_kmh"] = round(speed, 1)
    return CanonicalEvent(
        subject_id=subject_id,
        timestamp=ts,
        source=Source.APRS,
        event_type=EventType.POSITION,
        confidence=1.0,
        payload=payload,
    )


def entry_epoch(entry: dict) -> Optional[int]:
    """The ``lasttime`` epoch used for de-duplication."""
    raw = entry.get("lasttime") or entry.get("time")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_stale(epoch: Optional[int], now_epoch: float, max_age_hours: float) -> bool:
    """True if a fix is older than the max age (guard disabled when age <= 0)."""
    if epoch is None or max_age_hours <= 0:
        return False
    return (now_epoch - epoch) > max_age_hours * 3600.0


# --- Network adapter (isolates the blocking HTTP client) ----------------------

@dataclass
class AprsFiAdapter(Adapter):
    name: str = "aprs-fi"
    _stop: bool = False
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _last_pos: dict[int, tuple[float, float]] = field(default_factory=dict)
    _last_seen: dict[int, int] = field(default_factory=dict)  # subject_id -> lasttime epoch

    async def run(self, emit: EmitFn) -> None:
        self._loop = asyncio.get_running_loop()
        s = config.SETTINGS
        if not s.aprsfi_api_key:
            log.error("aprs.fi adapter enabled but CONFLUX_APRSFI_API_KEY is empty; not polling.")
            return
        while not self._stop:
            try:
                events = await asyncio.to_thread(self._poll_blocking)
                for event in events:
                    await emit(event)
            except Exception as exc:  # noqa: BLE001 — a poll error must not kill the loop
                log.warning("aprs.fi poll error: %s", exc)
            if self._stop:
                break
            await asyncio.sleep(config.scaled(s.aprsfi_poll_seconds))

    def _poll_blocking(self) -> list[CanonicalEvent]:
        s = config.SETTINGS
        subjects = service.subjects_public()
        callmap = build_callsign_map(subjects)
        names = [sub["callsign"] for sub in subjects if sub.get("callsign")]
        if not names:
            return []
        data = self._fetch(s, names[:20])  # aprs.fi accepts up to 20 names per call
        if data.get("result") != "ok":
            log.warning("aprs.fi API error: %s", data.get("description") or data)
            return []

        now_epoch = utcnow().timestamp()
        out: list[CanonicalEvent] = []
        for entry in parse_entries(data):
            sid = resolve_subject(str(entry.get("name", "")), callmap)
            if sid is None:
                continue
            epoch = entry_epoch(entry)
            if epoch is not None and self._last_seen.get(sid) == epoch:
                continue  # unchanged fix — don't re-emit (keeps absence honest)
            if is_stale(epoch, now_epoch, s.aprsfi_max_age_hours):
                continue  # long-stale cached position — not a current observation
            lat, lon = _to_float(entry.get("lat")), _to_float(entry.get("lng"))
            if lat is None or lon is None:
                continue
            cur = (lat, lon)
            moving = is_moving(_to_float(entry.get("speed")), self._last_pos.get(sid), cur,
                               s.aprs_speed_threshold_kmh, s.aprs_move_distance_m)
            event = entry_to_event(entry, sid, moving)
            if event is None:
                continue
            self._last_pos[sid] = cur
            if epoch is not None:
                self._last_seen[sid] = epoch
            out.append(event)
        if out:
            log.info("aprs.fi: %d new fix(es) for subjects %s",
                     len(out), sorted({e.subject_id for e in out}))
        return out

    def _fetch(self, s, names: list[str]) -> dict:
        params = urllib.parse.urlencode({
            "name": ",".join(names),
            "what": "loc",
            "apikey": s.aprsfi_api_key,
            "format": "json",
        })
        req = urllib.request.Request(f"{s.aprsfi_url}?{params}",
                                     headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed https host
            return json.loads(resp.read().decode("utf-8"))

    def stop(self) -> None:
        self._stop = True
