"""Shared async plumbing: the ``emit`` callback adapters use to ingest events.

Ingest is synchronous/transactional; we run it in a worker thread so the event
loop (serving HTTP + simulator) is never blocked.
"""

from __future__ import annotations

import asyncio

from . import service
from .models import CanonicalEvent


async def emit(event: CanonicalEvent) -> None:
    await asyncio.to_thread(service.ingest, event)
