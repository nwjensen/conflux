"""APRS-IS input adapter — real position input from the APRS network.

Design: the *transform* (parsed packet → canonical event, callsign → subject,
movement detection) is a set of pure functions that need no network and are unit
tested. The blocking ``aprslib`` client is isolated in :class:`APRSAdapter.run`,
which marshals events back onto the asyncio loop via the shared ``emit`` path —
exactly like the simulator. The core never learns that APRS exists.

Movement rule: a packet counts as *moving* if its reported speed exceeds a
threshold, or (when speed is absent/zero) if it has moved more than a distance
threshold from the subject's previous fix. That ``moving`` flag is what lets the
state engine resolve to OK.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from .. import config, service
from ..models import CanonicalEvent, EventType, Source
from .base import Adapter, EmitFn

log = logging.getLogger("conflux.aprs")


# --- Pure transforms (no network, unit-tested) --------------------------------

def base_callsign(call: str) -> str:
    """Strip the SSID: ``KE0ABC-9`` -> ``KE0ABC`` (uppercased)."""
    return call.split("-", 1)[0].strip().upper()


def build_callsign_map(subjects: list[dict]) -> dict[str, int]:
    """Map base callsign -> subject id for subjects that have a callsign."""
    out: dict[str, int] = {}
    for s in subjects:
        cs = s.get("callsign")
        if cs:
            out[base_callsign(cs)] = s["id"]
    return out


def resolve_subject(from_call: str, callmap: dict[str, int]) -> Optional[int]:
    return callmap.get(base_callsign(from_call))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def is_moving(speed_kmh: Optional[float],
              prev: Optional[tuple[float, float]],
              cur: tuple[float, float],
              speed_threshold_kmh: float,
              move_distance_m: float) -> bool:
    """Decide whether this fix represents movement."""
    if speed_kmh is not None and speed_kmh > speed_threshold_kmh:
        return True
    if prev is not None:
        return haversine_m(prev[0], prev[1], cur[0], cur[1]) > move_distance_m
    return False


def packet_to_event(packet: dict, subject_id: int, moving: bool) -> Optional[CanonicalEvent]:
    """Build a canonical position event from a parsed APRS packet.

    Returns ``None`` for packets without a usable position (e.g. messages,
    telemetry) — Phase 1 only consumes position from APRS.
    """
    lat, lon = packet.get("latitude"), packet.get("longitude")
    if lat is None or lon is None:
        return None
    payload = {"lat": round(float(lat), 5), "lon": round(float(lon), 5), "moving": moving}
    if packet.get("comment"):
        payload["place"] = str(packet["comment"])[:60]
    if packet.get("speed") is not None:
        payload["speed_kmh"] = round(float(packet["speed"]), 1)
    return CanonicalEvent(
        subject_id=subject_id,
        source=Source.APRS,
        event_type=EventType.POSITION,
        confidence=1.0,
        payload=payload,
    )


def default_filter(callmap: dict[str, int]) -> str:
    """Build a server-side budlist filter matching the tracked senders."""
    if not callmap:
        return "t/p"  # position packets; harmless default when no callsigns known
    return "b/" + "/".join(f"{cs}*" for cs in sorted(callmap))


# --- Network adapter (isolates the blocking aprslib client) -------------------

@dataclass
class APRSAdapter(Adapter):
    name: str = "aprs-is"
    _stop: bool = False
    _reconnect_fast: bool = False
    _last_pos: dict[int, tuple[float, float]] = field(default_factory=dict)
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _emit: Optional[EmitFn] = None
    _callmap: dict[str, int] = field(default_factory=dict)
    _ais: object = None

    async def run(self, emit: EmitFn) -> None:
        self._loop = asyncio.get_running_loop()
        self._emit = emit
        s = config.SETTINGS
        while not self._stop:
            try:
                await asyncio.to_thread(self._consume_blocking)
            except Exception as exc:  # noqa: BLE001 — network errors must not kill the loop
                log.warning("APRS-IS connection error: %s", exc)
            if self._stop:
                break
            # After an explicit refresh, reconnect promptly to pick up the new
            # roster/filter instead of waiting out the full backoff.
            delay = 0.5 if self._reconnect_fast else config.scaled(s.aprs_reconnect_seconds)
            self._reconnect_fast = False
            await asyncio.sleep(delay)

    def _consume_blocking(self) -> None:
        import aprslib  # lazy: only needed when the adapter is enabled

        s = config.SETTINGS
        self._callmap = build_callsign_map(service.subjects_public())
        filt = s.aprs_filter or default_filter(self._callmap)
        ais = aprslib.IS(s.aprs_callsign, passwd=s.aprs_passcode,
                         host=s.aprs_host, port=s.aprs_port)
        ais.set_filter(filt)
        log.info("APRS-IS connecting host=%s filter=%s subjects=%s",
                 s.aprs_host, filt, list(self._callmap))
        ais.connect()
        self._ais = ais
        try:
            ais.consumer(self._on_packet, raw=False, blocking=True, immortal=False)
        finally:
            self._ais = None
            ais.close()

    def _on_packet(self, packet: dict) -> None:
        try:
            from_call = packet.get("from")
            if not from_call:
                return
            subject_id = resolve_subject(from_call, self._callmap)
            if subject_id is None:
                return
            lat, lon = packet.get("latitude"), packet.get("longitude")
            if lat is None or lon is None:
                return
            cur = (float(lat), float(lon))
            moving = is_moving(packet.get("speed"), self._last_pos.get(subject_id), cur,
                               config.SETTINGS.aprs_speed_threshold_kmh,
                               config.SETTINGS.aprs_move_distance_m)
            self._last_pos[subject_id] = cur
            event = packet_to_event(packet, subject_id, moving)
            if event is not None and self._emit is not None and self._loop is not None:
                asyncio.run_coroutine_threadsafe(self._emit(event), self._loop)
        except Exception:  # noqa: BLE001 — one bad packet must not stop the stream
            log.exception("failed to handle APRS packet")

    def refresh(self) -> None:
        """Drop the current connection so ``run`` reconnects with a fresh roster.

        Safe to call from any thread: closing the socket unblocks the consumer,
        which returns through ``run``'s loop and rebuilds the callsign map and
        server-side filter from the current subjects.
        """
        self._reconnect_fast = True
        ais = self._ais
        if ais is not None:
            with contextlib.suppress(Exception):
                ais.close()

    def stop(self) -> None:
        self._stop = True
