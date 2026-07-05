"""HTTP surface.

Read-only endpoints (the Phase 1 UI contract) plus a PIN-guarded operator
override and a dev-only simulator control surface. The read endpoints never
expose diagnostics, frequencies, or raw traffic.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, service, views
from ..adapters.simulator import get_simulator
from ..models import Source, State

router = APIRouter()


# --- Read-only UI contract ----------------------------------------------------

@router.get("/subjects")
def get_subjects():
    return views.subjects()


@router.get("/state")
def get_all_state():
    return views.all_states()


@router.get("/state/{subject_id}")
def get_state(subject_id: int):
    return views.state_view(subject_id)


@router.get("/last_position/{subject_id}")
def get_last_position(subject_id: int):
    return views.last_position(subject_id)


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
