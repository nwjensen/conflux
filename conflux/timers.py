"""Pure time-window helpers: reachability classification and SMS scheduling.

Everything here is a pure function of ``now`` and persisted timestamps, which is
what makes Conflux restart- and failover-safe for free: after a failover the
same timestamps yield the same answers with no in-memory countdown to restore.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from . import config
from .models import Source


class Reach(str, Enum):
    """Spouse-friendly reachability classification for one channel."""

    SEEN_RECENTLY = "seen_recently"   # ✓
    STALE = "stale"                   # last seen, but past its window
    PENDING = "pending"               # sent, awaiting confirmation  (?)
    NEVER = "never"                   # no observation on record      (—)
    MANUAL = "manual"                 # manual-only channel (voice)


_ABSENCE_WINDOW = {
    Source.APRS: config.WINDOWS.aprs_absence,
    Source.MESH: config.WINDOWS.mesh_absence,
}


def reachability(source: Source, last_seen: Optional[datetime], now: datetime) -> Reach:
    """Classify a channel as seen-recently / stale / never."""
    if last_seen is None:
        return Reach.NEVER
    window = _ABSENCE_WINDOW.get(source)
    if window is None:
        # Passive/other sources: any observation counts as "seen".
        return Reach.SEEN_RECENTLY
    if (now - last_seen).total_seconds() <= config.scaled(window):
        return Reach.SEEN_RECENTLY
    return Reach.STALE


@dataclass(frozen=True)
class ReachabilityRow:
    source: str
    status: str
    last_at: Optional[datetime]


def next_sms_window(now: datetime, last_flush: Optional[datetime] = None) -> datetime:
    """When the next scheduled SMS window opens.

    Phase 1 default is clock-gating to the top and bottom of the hour (:00 / :30).
    For demos, ``CONFLUX_SMS_INTERVAL_SECONDS`` replaces clock-gating with a fixed
    cadence so messages arrive quickly.
    """
    interval = config.SETTINGS.sms_interval_seconds
    if interval > 0:
        base = last_flush or now
        return base + timedelta(seconds=interval)

    # Clock-gate to the next :00 or :30 boundary (in UTC).
    now = now.astimezone(timezone.utc)
    if now.minute < 30:
        nxt = now.replace(minute=30, second=0, microsecond=0)
    else:
        nxt = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    return nxt


def within_cooldown(last_sent: Optional[datetime], cooldown_seconds: float, now: datetime) -> bool:
    """True if a channel is still cooling down (suppress duplicate send)."""
    if last_sent is None:
        return False
    return (now - last_sent).total_seconds() < config.scaled(cooldown_seconds)
