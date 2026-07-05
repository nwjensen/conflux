"""Shared async plumbing: the ``emit`` callback adapters use to ingest events.

Ingest is synchronous/transactional; we run it in a worker thread so the event
loop (serving HTTP + simulator) is never blocked.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from . import service
from .models import CanonicalEvent


async def emit(event: CanonicalEvent) -> None:
    await asyncio.to_thread(service.ingest, event)


# --- Running-adapter registry -------------------------------------------------
# The APRS adapter is created and started in ``main``; the service layer reaches
# it here (without importing ``main``) to trigger a live reconnect when a
# subject's callsign changes.

_aprs_adapter: Optional[object] = None


def set_aprs_adapter(adapter: Optional[object]) -> None:
    global _aprs_adapter
    _aprs_adapter = adapter


def refresh_aprs() -> None:
    adapter = _aprs_adapter
    if adapter is not None:
        adapter.refresh()
