"""A built-in input simulator so Conflux runs end-to-end with no radios.

It emits APRS position updates for subjects that are "moving". Parking a subject
(via the sim-control API or an operator override) stops its position stream,
which lets the absence ladder play out: OK -> Delayed -> Need Contact. It also
confirms SMS deliveries so the reachability view resolves.

Everything here is *observation generation* only — it feeds the same ingest path
as a real adapter and has no special authority over state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from sqlalchemy import select

from .. import config, db, service
from ..db import Transmission
from ..models import (
    CanonicalEvent,
    Channel,
    EventType,
    Source,
    TxStatus,
    utcnow,
)
from .base import Adapter, EmitFn


@dataclass
class _SubjectSim:
    lat: float = 41.2565   # Omaha-ish default
    lon: float = -95.9345
    moving: bool = True


@dataclass
class InputSimulator(Adapter):
    name: str = "simulator"
    subjects: dict[int, _SubjectSim] = field(default_factory=dict)
    _stop: bool = False

    def _sim(self, subject_id: int) -> _SubjectSim:
        return self.subjects.setdefault(subject_id, _SubjectSim())

    # --- control surface (used by the /sim API) ---
    def set_moving(self, subject_id: int, moving: bool) -> None:
        self._sim(subject_id).moving = moving

    def is_moving(self, subject_id: int) -> bool:
        return self._sim(subject_id).moving

    async def emit_position(self, emit: EmitFn, subject_id: int) -> None:
        s = self._sim(subject_id)
        # Small drift so consecutive fixes look like real movement.
        s.lat += 0.0009
        s.lon += 0.0006
        await emit(CanonicalEvent(
            subject_id=subject_id,
            source=Source.APRS,
            event_type=EventType.POSITION,
            payload={"lat": round(s.lat, 5), "lon": round(s.lon, 5),
                     "moving": True, "place": "en route"},
        ))

    async def emit_inbound_message(self, emit: EmitFn, subject_id: int,
                                   source: Source = Source.MESH) -> None:
        await emit(CanonicalEvent(
            subject_id=subject_id,
            source=source,
            event_type=EventType.MESSAGE,
            payload={"text": "OK. Moving normally."},
        ))

    async def run(self, emit: EmitFn) -> None:
        interval = max(1.0, config.scaled(config.WINDOWS.aprs_observation))
        while not self._stop:
            for sid in service.active_subject_ids():
                if self._sim(sid).moving:
                    await self.emit_position(emit, sid)
            await self._confirm_deliveries(emit)
            await asyncio.sleep(interval)

    async def _confirm_deliveries(self, emit: EmitFn) -> None:
        """Confirm SMS sends after the delivery-confirmation window elapses."""
        cutoff = utcnow() - timedelta(seconds=config.scaled(
            config.WINDOWS.sms_delivery_confirmation) * 0.2 + 1)
        with db.session_scope() as session:
            rows = session.execute(
                select(Transmission).where(
                    Transmission.channel == Channel.SMS.value,
                    Transmission.status == TxStatus.SENT.value,
                    Transmission.sent_at.is_not(None),
                    Transmission.sent_at <= cutoff,
                )
            ).scalars().all()
            subject_ids = [r.subject_id for r in rows]
        for sid in subject_ids:
            await emit(CanonicalEvent(
                subject_id=sid,
                source=Source.SMS,
                event_type=EventType.DELIVERY,
                payload={"status": "confirmed"},
            ))

    def stop(self) -> None:
        self._stop = True


# Process-wide simulator instance (also the sim-control target for the API).
SIMULATOR: Optional[InputSimulator] = None


def get_simulator() -> InputSimulator:
    global SIMULATOR
    if SIMULATOR is None:
        SIMULATOR = InputSimulator()
    return SIMULATOR
