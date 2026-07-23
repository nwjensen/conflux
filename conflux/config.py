"""Authoritative Phase 1 constants and runtime settings.

All time windows come straight from ``Conflux_Phase1_Timer_Window_Definitions``.
They are expressed here in **seconds** and are the single source of truth for the
rest of the system. Nothing about timing is adaptive or learned in Phase 1.

``TIME_SCALE`` lets a demo compress every window by a constant factor so the
absence-driven transitions (OK -> Delayed -> Need Contact) are observable in
seconds instead of tens of minutes. It never changes *relative* behaviour.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MINUTE = 60


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


# A constant multiplier applied to every window. 1.0 == real-world timing.
# e.g. CONFLUX_TIME_SCALE=0.05 turns the 10-minute APRS absence window into 30s.
TIME_SCALE: float = _float_env("CONFLUX_TIME_SCALE", 1.0)


def scaled(seconds: float) -> float:
    """Apply the global demo time-scale to a window defined in real seconds."""
    return seconds * TIME_SCALE


@dataclass(frozen=True)
class Windows:
    """Time windows, in real-world seconds (apply :func:`scaled` at use sites)."""

    # --- APRS (primary position source) ---
    aprs_observation: float = 5 * MINUTE
    aprs_absence: float = 10 * MINUTE          # note absence -> Delayed (if prior movement)
    aprs_extended: float = 20 * MINUTE         # permit escalation -> Need Contact

    # --- LoRa mesh (Meshtastic / MeshCore) ---
    mesh_observation: float = 10 * MINUTE
    mesh_absence: float = 20 * MINUTE          # reduced reachability
    mesh_extended: float = 40 * MINUTE         # permit escalation -> Need Contact

    # --- SMS ---
    sms_delivery_confirmation: float = 5 * MINUTE

    # --- CW (Morse) ---
    cw_interval: float = 60

    # --- Cooldowns: minimum spacing between repeated sends on a channel ---
    aprs_cooldown: float = 5 * MINUTE
    mesh_cooldown: float = 5 * MINUTE


WINDOWS = Windows()


@dataclass(frozen=True)
class Retention:
    """Local-only retention windows, in seconds."""

    event_logs: float = 72 * 3600
    state_history: float = 30 * 24 * 3600
    transcripts: float = 24 * 3600
    delivery_logs: float = 7 * 24 * 3600


RETENTION = Retention()


@dataclass(frozen=True)
class Settings:
    """Deployment/runtime settings (environment driven)."""

    database_url: str = os.environ.get("CONFLUX_DATABASE_URL", "sqlite:///./conflux.db")

    # Operator PIN guarding the override endpoint.
    override_pin: str = os.environ.get("CONFLUX_OVERRIDE_PIN", "0000")

    # Background evaluation cadence (seconds of wall clock).
    tick_interval: float = _float_env("CONFLUX_TICK_INTERVAL", 5.0)

    # CW auto-keying is opt-in (Phase 1 default: off).
    cw_enabled: bool = os.environ.get("CONFLUX_CW_ENABLED", "false").lower() == "true"

    # SMS scheduling. Phase 1 is clock-gated to :00 / :30. For demos an explicit
    # interval (seconds) can replace clock-gating so windows arrive quickly.
    sms_interval_seconds: int = _int_env("CONFLUX_SMS_INTERVAL_SECONDS", 0)

    # Built-in input simulator (drives subjects without real radios).
    simulator_enabled: bool = os.environ.get("CONFLUX_SIMULATOR", "true").lower() == "true"

    # Subjects seeded on first start when the registry is empty.
    # Format: "Name:CALLSIGN,Name:CALLSIGN". Callsign optional.
    seed_subjects: str = os.environ.get(
        "CONFLUX_SEED_SUBJECTS", "Dad:KE0ABC,Mom:KE0DEF,Teen:KE0GHI"
    )

    # --- APRS-IS input adapter (real radio input via the APRS-IS network) ---
    # Off by default; the simulator covers development. Enable to ingest live
    # position reports for subjects whose callsign matches a packet's sender.
    aprs_enabled: bool = os.environ.get("CONFLUX_APRS_ENABLED", "false").lower() == "true"
    aprs_host: str = os.environ.get("CONFLUX_APRS_HOST", "rotate.aprs2.net")
    aprs_port: int = _int_env("CONFLUX_APRS_PORT", 14580)
    # Login callsign + passcode. "-1" is receive-only (no transmit rights).
    aprs_callsign: str = os.environ.get("CONFLUX_APRS_CALLSIGN", "N0CALL")
    aprs_passcode: str = os.environ.get("CONFLUX_APRS_PASSCODE", "-1")
    # Server-side filter. Empty -> built automatically from subject callsigns.
    aprs_filter: str = os.environ.get("CONFLUX_APRS_FILTER", "")
    # Movement detection thresholds.
    aprs_speed_threshold_kmh: float = _float_env("CONFLUX_APRS_SPEED_KMH", 3.0)
    aprs_move_distance_m: float = _float_env("CONFLUX_APRS_MOVE_M", 50.0)
    aprs_reconnect_seconds: float = _float_env("CONFLUX_APRS_RECONNECT", 30.0)

    # --- aprs.fi poller (position via the aprs.fi HTTP API) ------------------
    # A pull alternative to APRS-IS: works when a subject's position lives in
    # aprs.fi (e.g. its browser "share location" / web-station feature) but is
    # never transmitted onto APRS-IS. Needs a free aprs.fi API key. Movement
    # thresholds and callsign->subject matching are shared with the APRS adapter.
    aprsfi_enabled: bool = os.environ.get("CONFLUX_APRSFI_ENABLED", "false").lower() == "true"
    aprsfi_api_key: str = os.environ.get("CONFLUX_APRSFI_API_KEY", "")
    aprsfi_url: str = os.environ.get("CONFLUX_APRSFI_URL", "https://api.aprs.fi/api/get")
    # aprs.fi asks callers not to poll faster than ~1/min; keep a safe floor.
    aprsfi_poll_seconds: float = max(30.0, _float_env("CONFLUX_APRSFI_POLL", 60.0))
    # aprs.fi returns the last-known position regardless of age. Ignore fixes
    # older than this so a long-stale cached position is never ingested as if it
    # were current (0 disables the guard).
    aprsfi_max_age_hours: float = _float_env("CONFLUX_APRSFI_MAX_AGE_HOURS", 24.0)

    # --- Basemap tiles (Family Command Hub map) ------------------------------
    # The hub fetches tiles from Conflux, never from the internet directly, so
    # the map keeps drawing previously-viewed areas while the link is down.
    tile_url: str = os.environ.get(
        "CONFLUX_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    tile_cache_dir: str = os.environ.get("CONFLUX_TILE_CACHE_DIR", "/var/lib/conflux/tiles")
    # Soft cap; least-recently-written tiles are evicted past it.
    tile_cache_mb: float = _float_env("CONFLUX_TILE_CACHE_MB", 256.0)
    # Re-fetch a cached tile once it is this old (0 = cache never expires).
    tile_max_age_days: float = _float_env("CONFLUX_TILE_MAX_AGE_DAYS", 30.0)
    # Off = serve only what is already cached (fully offline basemap).
    tile_upstream_enabled: bool = os.environ.get("CONFLUX_TILE_UPSTREAM", "true").lower() == "true"
    tile_max_zoom: int = _int_env("CONFLUX_TILE_MAX_ZOOM", 19)


SETTINGS = Settings()
