"""The Phase 1 Canonical Message Catalog as data.

These are **fixed strings**. Identical semantic meaning across every transport;
calm, factual, non-alarmist; no interpretation. Rendering per channel is a pure
lookup so the same catalog drives APRS, mesh, SMS, CW, and the Family Hub.

Guiding rule: *If a message requires explanation, it is not allowed in Phase 1.*
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Channel, State


@dataclass(frozen=True)
class CatalogEntry:
    canonical_meaning: str
    aprs: str
    mesh: str
    sms: str
    cw: str
    hub_status: str
    hub_details: str


CATALOG: dict[State, CatalogEntry] = {
    State.OK: CatalogEntry(
        canonical_meaning="Normal movement or stopped briefly. No concern.",
        aprs="OK. Moving normally.",
        mesh="OK. Moving normally.",
        sms="OK. Moving normally.",
        cw="K",
        hub_status="OK",
        hub_details="Moving normally",
    ),
    State.DELAYED: CatalogEntry(
        canonical_meaning="Safe, but movement is slowed or paused.",
        aprs="Delayed. Safe.",
        mesh="Delayed. Safe.",
        sms="Delayed. Safe.",
        cw="D",
        hub_status="Delayed",
        hub_details="Safe, slowed or stopped",
    ),
    State.NEED_CONTACT: CatalogEntry(
        canonical_meaning="Attempting to establish communication.",
        aprs="Need contact.",
        mesh="Need contact.",
        sms="Trying to reach you.",
        cw="R",
        hub_status="Need Contact",
        hub_details="Attempting communication",
    ),
    State.NEED_HELP: CatalogEntry(
        canonical_meaning="Assistance required, not immediately life-threatening.",
        aprs="Need help.",
        mesh="Need help.",
        sms="Need help. Not an emergency.",
        cw="H",
        hub_status="Need Help",
        hub_details="Assistance required",
    ),
    State.EMERGENCY: CatalogEntry(
        canonical_meaning="Immediate assistance required.",
        aprs="EMERGENCY.",
        mesh="EMERGENCY.",
        sms="EMERGENCY. Need help now.",
        cw="SOS",
        hub_status="Emergency",
        hub_details="Immediate help required",
    ),
}


_CHANNEL_FIELD = {
    Channel.APRS: "aprs",
    Channel.MESH: "mesh",
    Channel.SMS: "sms",
    Channel.CW: "cw",
}


def render(state: State, channel: Channel) -> str:
    """Return the fixed Phase 1 string for ``state`` on ``channel``."""
    entry = CATALOG[state]
    if channel in _CHANNEL_FIELD:
        return getattr(entry, _CHANNEL_FIELD[channel])
    if channel == Channel.HUB:
        return f"{entry.hub_status}: {entry.hub_details}"
    if channel == Channel.VOICE:
        return entry.canonical_meaning
    raise ValueError(f"No catalog rendering for channel {channel}")
