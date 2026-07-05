"""Adapter contract.

Every input (APRS, Meshtastic, MeshCore, SDR, SMS delivery, ...) is an Adapter
that produces :class:`CanonicalEvent` objects and hands them to an ``emit``
callback. The core never imports a radio library; it only ever sees canonical
events. Real hardware adapters are added in later phases behind this same
interface.
"""

from __future__ import annotations

import abc
from typing import Awaitable, Callable

from ..models import CanonicalEvent

EmitFn = Callable[[CanonicalEvent], Awaitable[None]]


class Adapter(abc.ABC):
    name: str = "adapter"

    @abc.abstractmethod
    async def run(self, emit: EmitFn) -> None:
        """Run forever, calling ``emit`` for each observation produced."""
        raise NotImplementedError
