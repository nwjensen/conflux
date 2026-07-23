"""Basemap tiles: a caching proxy so the map survives losing the internet.

The Family Command Hub draws observed positions on an OpenStreetMap basemap.
Pointing the browser straight at an upstream tile server would leave the map
blank during exactly the conditions Conflux exists for, so the browser only ever
talks to Conflux: we serve tiles from a local disk cache and fill that cache
from upstream as areas are actually viewed. Once an area has been looked at, it
keeps drawing with no internet at all.

Tiles are decoration, never evidence. Nothing here participates in state, and a
missing tile degrades the basemap only — the observed fixes still render.
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from . import config
from .models import utcnow

log = logging.getLogger("conflux.tiles")

_USER_AGENT = "Conflux/1.0 (+https://github.com/nwjensen/conflux)"

# Upstream politeness: a handful of parallel fetches is plenty for one browser
# panning a map, and keeps us well inside public tile-server usage policies.
_MAX_UPSTREAM_CONCURRENCY = 4
_semaphore: Optional[asyncio.Semaphore] = None

# Pruning walks the whole cache tree, so amortize it over many writes.
_PRUNE_EVERY = 200
_writes_since_prune = 0

# Set once when the cache directory turns out to be unwritable, so a read-only
# deployment logs the problem once and then quietly runs proxy-only.
_cache_disabled = False


# --- Pure helpers (no I/O, unit-tested) ---------------------------------------

def is_valid_tile(z: int, x: int, y: int, max_zoom: Optional[int] = None) -> bool:
    """True if (z, x, y) addresses a real tile in the Web Mercator pyramid.

    Path traversal is already impossible (FastAPI hands us ints), but bounding
    the coordinates keeps a typo or a crawler from filling the cache with
    directories that can never correspond to a tile.
    """
    limit = config.SETTINGS.tile_max_zoom if max_zoom is None else max_zoom
    if z < 0 or z > limit:
        return False
    span = 1 << z
    return 0 <= x < span and 0 <= y < span


def cache_path(cache_dir: Path, z: int, x: int, y: int) -> Path:
    return Path(cache_dir) / str(z) / str(x) / f"{y}.png"


def is_fresh(path: Path, max_age_days: float, now: Optional[float] = None) -> bool:
    """True if a cached tile is young enough to serve without re-fetching.

    ``max_age_days <= 0`` disables expiry entirely: the cache is then treated as
    permanent, which is the right choice for a deployment that expects to spend
    long stretches offline.
    """
    if max_age_days <= 0:
        return True
    try:
        age = (now if now is not None else utcnow().timestamp()) - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age_days * 86400


def upstream_url(template: str, z: int, x: int, y: int) -> str:
    return template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))


def prune(cache_dir: Path, max_bytes: float) -> int:
    """Evict least-recently-modified tiles until the cache fits ``max_bytes``.

    Returns the number of files removed. A cap of 0 or less means unbounded.
    """
    if max_bytes <= 0 or not Path(cache_dir).is_dir():
        return 0
    files: list[tuple[float, int, Path]] = []
    total = 0
    for path in Path(cache_dir).rglob("*.png"):
        try:
            st = path.stat()
        except OSError:
            continue
        files.append((st.st_mtime, st.st_size, path))
        total += st.st_size
    if total <= max_bytes:
        return 0
    files.sort(key=lambda f: f[0])  # oldest first
    removed = 0
    for _mtime, size, path in files:
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    log.info("tile cache pruned: removed %d tile(s), now ~%.1f MB", removed, total / 1e6)
    return removed


# --- Disk + network (blocking; always called in a worker thread) --------------

def read_cached(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except OSError:
        return None


def store(path: Path, data: bytes) -> None:
    """Write a tile atomically, degrading to proxy-only if the cache is unwritable."""
    global _writes_since_prune, _cache_disabled
    if _cache_disabled:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as exc:
        _cache_disabled = True
        log.warning("tile cache unwritable (%s); serving tiles without caching. "
                    "Set CONFLUX_TILE_CACHE_DIR to a writable path to restore "
                    "offline map coverage.", exc)
        return
    _writes_since_prune += 1
    if _writes_since_prune >= _PRUNE_EVERY:
        _writes_since_prune = 0
        prune(path.parents[2], config.SETTINGS.tile_cache_mb * 1e6)


def fetch_upstream(z: int, x: int, y: int) -> bytes:
    s = config.SETTINGS
    req = urllib.request.Request(upstream_url(s.tile_url, z, x, y),
                                 headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — configured host
        return resp.read()


# --- Orchestration ------------------------------------------------------------

async def get_tile(z: int, x: int, y: int,
                   fetch: Callable[[int, int, int], bytes] = fetch_upstream) -> Optional[bytes]:
    """Return PNG bytes for one tile, or ``None`` if it can't be produced.

    Order of preference: a fresh cached tile, then upstream, then a *stale*
    cached tile. That last fallback is the point of the whole module — when the
    link is down, the map keeps drawing everywhere the family has already looked.
    """
    global _semaphore
    s = config.SETTINGS
    path = cache_path(Path(s.tile_cache_dir), z, x, y)

    if await asyncio.to_thread(is_fresh, path, s.tile_max_age_days):
        cached = await asyncio.to_thread(read_cached, path)
        if cached:
            return cached

    if s.tile_upstream_enabled:
        if _semaphore is None:
            _semaphore = asyncio.Semaphore(_MAX_UPSTREAM_CONCURRENCY)
        try:
            async with _semaphore:
                data = await asyncio.to_thread(fetch, z, x, y)
            if data:
                await asyncio.to_thread(store, path, data)
                return data
        except Exception as exc:  # noqa: BLE001 — any upstream failure falls back to cache
            log.debug("tile %s/%s/%s upstream failed: %s", z, x, y, exc)

    return await asyncio.to_thread(read_cached, path)
