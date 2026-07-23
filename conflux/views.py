"""Read models for the Family Command Hub API.

Every function derives a spouse-friendly, facts-only view from the append-only
log. These back the read-only endpoints in the UI contract:
    /state /last_position /reachability /recent_messages /transmission_log /timeline
No advice, no speculation, no diagnostics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from . import db, timers
from .db import Event, StateTransition, Subject, Transmission
from .message_catalog import CATALOG
from .models import Channel, EventType, Source, State, TxStatus, utcnow


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def subjects() -> list[dict[str, Any]]:
    with db.session_scope() as session:
        rows = session.execute(
            select(Subject).where(Subject.active.is_(True)).order_by(Subject.id)
        ).scalars().all()
        return [{"id": s.id, "name": s.name, "callsign": s.callsign} for s in rows]


def state_view(subject_id: int) -> dict[str, Any]:
    with db.session_scope() as session:
        subj = session.get(Subject, subject_id)
        state, entered = db.current_state(session, subject_id)
        last = session.execute(
            select(StateTransition)
            .where(StateTransition.subject_id == subject_id)
            .order_by(StateTransition.at.desc()).limit(1)
        ).scalar_one_or_none()
        entry = CATALOG[state]
        return {
            "subject_id": subject_id,
            "name": subj.name if subj else None,
            "callsign": subj.callsign if subj else None,
            "state": state.value,
            "emoji": state.emoji,
            "label": state.label,
            "details": entry.hub_details,
            "reason": last.reason if last else "Starting state.",
            "since": _iso(entered),
        }


def all_states() -> list[dict[str, Any]]:
    return [state_view(s["id"]) for s in subjects()]


def last_position(subject_id: int) -> dict[str, Any]:
    with db.session_scope() as session:
        row = session.execute(
            select(Event)
            .where(Event.subject_id == subject_id,
                   Event.event_type == EventType.POSITION.value)
            .order_by(Event.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return {"subject_id": subject_id, "known": False,
                    "location": None, "movement": "Unknown", "at": None}
        payload = row.payload or {}
        movement = "Moving" if payload.get("moving") else "Stopped"
        loc = payload.get("place") or _coords(payload)
        return {
            "subject_id": subject_id,
            "known": True,
            "location": loc,
            "lat": payload.get("lat"),
            "lon": payload.get("lon"),
            "movement": movement,
            "at": _iso(row.timestamp),
        }


def track(subject_id: int, limit: int = 200) -> dict[str, Any]:
    """The observed position fixes for one subject, oldest first.

    Every entry is a report Conflux actually received. Nothing is interpolated,
    smoothed, or inferred: consumers may join the points in order, but the
    segments between them were never observed and must not be presented as a
    route. ``distinct_points`` lets the UI say "132 fixes at 1 location" instead
    of implying movement that no fix supports.
    """
    with db.session_scope() as session:
        rows = session.execute(
            select(Event)
            .where(Event.subject_id == subject_id,
                   Event.event_type == EventType.POSITION.value)
            .order_by(Event.timestamp.desc()).limit(limit)
        ).scalars().all()

        fixes: list[dict[str, Any]] = []
        for row in reversed(rows):  # oldest first for drawing
            payload = row.payload or {}
            lat, lon = payload.get("lat"), payload.get("lon")
            if lat is None or lon is None:
                continue
            fixes.append({
                "at": _iso(row.timestamp),
                "lat": lat,
                "lon": lon,
                "moving": bool(payload.get("moving")),
                "speed_kmh": payload.get("speed_kmh"),
                "place": payload.get("place"),
                "source": row.source.upper(),
            })
        return {
            "subject_id": subject_id,
            "count": len(fixes),
            "distinct_points": len({(f["lat"], f["lon"]) for f in fixes}),
            "fixes": fixes,
        }


def _coords(payload: dict) -> Optional[str]:
    lat, lon = payload.get("lat"), payload.get("lon")
    if lat is None or lon is None:
        return None
    return f"{lat:.4f}, {lon:.4f}"


_REACH_SYMBOL = {
    timers.Reach.SEEN_RECENTLY: "✓ Seen recently",
    timers.Reach.STALE: "· Not seen recently",
    timers.Reach.PENDING: "? Pending / Unknown",
    timers.Reach.NEVER: "— No data",
    timers.Reach.MANUAL: "— Manual only",
}


def reachability(subject_id: int) -> dict[str, Any]:
    now = utcnow()
    with db.session_scope() as session:
        def last_seen(source: Source) -> Optional[datetime]:
            return session.execute(
                select(Event.timestamp)
                .where(Event.subject_id == subject_id, Event.source == source.value)
                .order_by(Event.timestamp.desc()).limit(1)
            ).scalar_one_or_none()

        rows = []
        for source in (Source.APRS, Source.MESH):
            seen = last_seen(source)
            reach = timers.reachability(source, seen, now)
            rows.append({"channel": source.value.upper(),
                         "status": _REACH_SYMBOL[reach],
                         "last_at": _iso(seen)})

        sms = db.last_transmission(session, subject_id, Channel.SMS)
        if sms is None:
            rows.append({"channel": "SMS", "status": _REACH_SYMBOL[timers.Reach.NEVER],
                         "last_at": None})
        else:
            reach = timers.Reach.SEEN_RECENTLY if sms.status == TxStatus.CONFIRMED.value \
                else timers.Reach.PENDING
            rows.append({"channel": "SMS", "status": _REACH_SYMBOL[reach],
                         "last_at": _iso(sms.sent_at or sms.created_at)})

        rows.append({"channel": "Voice", "status": _REACH_SYMBOL[timers.Reach.MANUAL],
                     "last_at": None})
        return {
            "subject_id": subject_id,
            "channels": rows,
            "note": "“Pending / Unknown” means we did not receive a "
                    "confirmation. It does not mean failure.",
        }


def recent_messages(subject_id: int, limit: int = 20) -> dict[str, Any]:
    with db.session_scope() as session:
        inbound = session.execute(
            select(Event)
            .where(Event.subject_id == subject_id,
                   Event.event_type == EventType.MESSAGE.value)
            .order_by(Event.timestamp.desc()).limit(limit)
        ).scalars().all()
        outbound = session.execute(
            select(Transmission)
            .where(Transmission.subject_id == subject_id,
                   Transmission.status.in_([TxStatus.SENT.value, TxStatus.CONFIRMED.value]))
            .order_by(Transmission.created_at.desc()).limit(limit)
        ).scalars().all()

        items: list[dict[str, Any]] = []
        for e in inbound:
            items.append({"at": e.timestamp, "direction": "Received",
                          "transport": e.source.upper(),
                          "text": (e.payload or {}).get("text", "")})
        for t in outbound:
            confirmed = t.status == TxStatus.CONFIRMED.value
            items.append({"at": t.sent_at or t.created_at, "direction": "Sent",
                          "transport": t.channel.upper(), "text": t.message,
                          "note": None if confirmed else "Delivery not confirmed"})
        items.sort(key=lambda x: x["at"], reverse=True)
        for it in items:
            it["at"] = _iso(it["at"])
        return {"subject_id": subject_id, "messages": items[:limit]}


def transmission_log(subject_id: int, limit: int = 50) -> dict[str, Any]:
    with db.session_scope() as session:
        rows = session.execute(
            select(Transmission)
            .where(Transmission.subject_id == subject_id)
            .order_by(Transmission.created_at.desc()).limit(limit)
        ).scalars().all()
        return {"subject_id": subject_id, "transmissions": [
            {"at": _iso(r.sent_at or r.created_at), "channel": r.channel.upper(),
             "state": r.state, "message": r.message, "status": r.status,
             "scheduled_for": _iso(r.scheduled_for)}
            for r in rows
        ]}


def timeline(subject_id: int, limit: int = 40) -> dict[str, Any]:
    with db.session_scope() as session:
        transitions = session.execute(
            select(StateTransition)
            .where(StateTransition.subject_id == subject_id)
            .order_by(StateTransition.at.desc()).limit(limit)
        ).scalars().all()
        positions = session.execute(
            select(Event)
            .where(Event.subject_id == subject_id,
                   Event.event_type == EventType.POSITION.value)
            .order_by(Event.timestamp.desc()).limit(limit)
        ).scalars().all()
        sends = session.execute(
            select(Transmission)
            .where(Transmission.subject_id == subject_id,
                   Transmission.status.in_([TxStatus.SENT.value, TxStatus.CONFIRMED.value]))
            .order_by(Transmission.created_at.desc()).limit(limit)
        ).scalars().all()

        items: list[dict[str, Any]] = []
        for t in transitions:
            st = State(t.to_state)
            items.append({"at": t.at, "kind": "state",
                          "text": f"State: {st.emoji} {st.label}", "detail": t.reason})
        for e in positions:
            items.append({"at": e.timestamp, "kind": "position",
                          "text": "Position update received", "detail": None})
        for s in sends:
            items.append({"at": s.sent_at or s.created_at, "kind": "sent",
                          "text": f"Sent ({s.channel.upper()}): “{s.message}”",
                          "detail": None})
        items.sort(key=lambda x: x["at"], reverse=True)
        for it in items:
            it["at"] = _iso(it["at"])
        return {"subject_id": subject_id, "events": items[:limit]}
