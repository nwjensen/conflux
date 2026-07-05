"""Domain vocabulary and the canonical event schema.

These are the fixed enumerations and the normalized event shape from the
Technical Specification. Everything downstream (state engine, orchestrator,
persistence, API) speaks in these terms only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Timezone-aware current time. All timestamps in Conflux are UTC."""
    return datetime.now(timezone.utc)


class State(str, Enum):
    """The fixed set of human-centered states (order == severity)."""

    OK = "OK"
    DELAYED = "DELAYED"
    NEED_CONTACT = "NEED_CONTACT"
    NEED_HELP = "NEED_HELP"
    EMERGENCY = "EMERGENCY"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    @property
    def emoji(self) -> str:
        return _EMOJI[self]

    @property
    def label(self) -> str:
        return _LABEL[self]


_SEVERITY = {
    State.OK: 0,
    State.DELAYED: 1,
    State.NEED_CONTACT: 2,
    State.NEED_HELP: 3,
    State.EMERGENCY: 4,
}
_EMOJI = {
    State.OK: "🟢",
    State.DELAYED: "🟡",
    State.NEED_CONTACT: "🟠",
    State.NEED_HELP: "🔴",
    State.EMERGENCY: "🚨",
}
_LABEL = {
    State.OK: "OK",
    State.DELAYED: "Delayed",
    State.NEED_CONTACT: "Need Contact",
    State.NEED_HELP: "Need Help",
    State.EMERGENCY: "Emergency",
}


class Source(str, Enum):
    """Where an observation came from."""

    APRS = "aprs"
    MESH = "mesh"
    HAM = "ham"
    DMR = "dmr"
    P25 = "p25"
    SMS = "sms"
    CW = "cw"
    HUMAN = "human"     # operator override / manual input
    SYSTEM = "system"   # Conflux-initiated


class EventType(str, Enum):
    """The kind of thing an event represents."""

    POSITION = "position"
    MESSAGE = "message"
    PRESENCE = "presence"
    ABSENCE = "absence"
    DELIVERY = "delivery"
    TRANSCRIPT = "transcript"
    STATUS = "status"      # explicit human-sent status
    OVERRIDE = "override"  # operator sets state directly


class Channel(str, Enum):
    """Outbound signaling channels."""

    APRS = "aprs"
    MESH = "mesh"
    SMS = "sms"
    CW = "cw"
    VOICE = "voice"
    HUB = "hub"


class TxStatus(str, Enum):
    """Lifecycle of an outbound transmission."""

    PENDING = "pending"      # queued (e.g. SMS awaiting a scheduled window)
    SENT = "sent"            # handed to the transport
    CONFIRMED = "confirmed"  # delivery confirmed (re-ingested)
    FAILED = "failed"        # delivery not confirmed / failed
    SUPPRESSED = "suppressed"  # deduped: state unchanged, not re-sent


class CanonicalEvent(BaseModel):
    """The normalized event every adapter produces (Technical Spec §3.2).

    ``subject_id`` is a Conflux extension: Phase 1 tracks *n* subjects, so every
    observation is attributed to exactly one subject.
    """

    subject_id: int
    timestamp: datetime = Field(default_factory=utcnow)
    source: Source
    event_type: EventType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": False}

    # --- convenience accessors used by the engine ---
    @property
    def moving(self) -> Optional[bool]:
        """For position events: whether movement was observed, if reported."""
        val = self.payload.get("moving")
        return bool(val) if val is not None else None

    @property
    def target_state(self) -> Optional[State]:
        """For override/status events carrying an explicit target state."""
        raw = self.payload.get("state")
        if raw is None:
            return None
        try:
            return State(raw)
        except ValueError:
            return None
