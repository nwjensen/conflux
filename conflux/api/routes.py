"""HTTP surface.

Read-only endpoints (the Phase 1 UI contract) plus a PIN-guarded operator
override and a dev-only simulator control surface. The read endpoints never
expose diagnostics, frequencies, or raw traffic.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import config, service, tiles, views
from ..adapters.simulator import get_simulator
from ..models import Source, State

router = APIRouter()


# --- Read-only UI contract ----------------------------------------------------

@router.get("/subjects")
def get_subjects(all: bool = False):
    """Active subjects by default; ``?all=true`` includes deactivated ones for the editor."""
    if all:
        return service.list_subjects(include_inactive=True)
    return views.subjects()


# --- Subject profile management -----------------------------------------------

class SubjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    callsign: Optional[str] = Field(None, max_length=16)
    active: bool = True


@router.post("/subjects")
def post_subject(req: SubjectRequest):
    try:
        sid = service.create_subject(req.name, req.callsign, active=req.active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": sid, "name": req.name.strip(),
            "callsign": service.normalize_callsign(req.callsign), "active": req.active}


@router.patch("/subjects/{subject_id}")
def patch_subject(subject_id: int, req: SubjectRequest):
    try:
        return service.update_subject(subject_id, req.name, req.callsign, req.active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/state")
def get_all_state():
    return views.all_states()


@router.get("/state/{subject_id}")
def get_state(subject_id: int):
    return views.state_view(subject_id)


@router.get("/last_position/{subject_id}")
def get_last_position(subject_id: int):
    return views.last_position(subject_id)


@router.get("/track/{subject_id}")
def get_track(subject_id: int, limit: int = 200):
    """Observed position fixes for the hub map (oldest first, newest last)."""
    return views.track(subject_id, limit=max(1, min(limit, 500)))


@router.get("/reachability/{subject_id}")
def get_reachability(subject_id: int):
    return views.reachability(subject_id)


@router.get("/recent_messages/{subject_id}")
def get_recent_messages(subject_id: int):
    return views.recent_messages(subject_id)


@router.get("/transmission_log/{subject_id}")
def get_transmission_log(subject_id: int):
    return views.transmission_log(subject_id)


@router.get("/timeline/{subject_id}")
def get_timeline(subject_id: int):
    return views.timeline(subject_id)


# --- Basemap tiles (cached proxy; see conflux.tiles) --------------------------

@router.get("/tiles/{z}/{x}/{y}.png")
async def get_tile(z: int, x: int, y: int):
    if not tiles.is_valid_tile(z, x, y):
        raise HTTPException(status_code=404, detail="No such tile.")
    data = await tiles.get_tile(z, x, y)
    if data is None:
        # Not cached and upstream unreachable. The hub draws its own placeholder;
        # observed positions still render on top of the gap.
        raise HTTPException(status_code=503, detail="Tile unavailable offline.")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


# --- Operator override (PIN protected) ----------------------------------------

class OverrideRequest(BaseModel):
    state: State
    pin: str
    immediate: bool = False


@router.post("/override/{subject_id}")
def post_override(subject_id: int, req: OverrideRequest):
    if req.pin != config.SETTINGS.override_pin:
        raise HTTPException(status_code=403, detail="Invalid PIN.")
    transition = service.override(subject_id, req.state, immediate=req.immediate)
    return {
        "subject_id": subject_id,
        "applied_state": req.state.value,
        "changed": transition is not None,
        "warning": "This will send messages now." if req.immediate else None,
    }


# --- Simulator control (dev only) ---------------------------------------------

class MovingRequest(BaseModel):
    moving: bool = Field(..., description="True keeps position updates flowing; "
                                          "False parks the subject to demo absence.")


@router.get("/sim")
def sim_status():
    sim = get_simulator()
    return {"enabled": config.SETTINGS.simulator_enabled,
            "subjects": {sid: sim.is_moving(sid) for sid in service.active_subject_ids()}}


@router.post("/sim/{subject_id}/moving")
def sim_set_moving(subject_id: int, req: MovingRequest):
    get_simulator().set_moving(subject_id, req.moving)
    return {"subject_id": subject_id, "moving": req.moving}


@router.post("/sim/{subject_id}/inbound_message")
async def sim_inbound_message(subject_id: int):
    from ..app_state import emit  # late import to avoid a cycle at import time
    await get_simulator().emit_inbound_message(emit, subject_id, source=Source.MESH)
    return {"subject_id": subject_id, "sent": True}
