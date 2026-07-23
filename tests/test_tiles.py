"""Basemap tile cache: coordinate validation, expiry, eviction, offline fallback.

The behaviour that matters is the last one — with upstream unreachable, a
previously-cached tile must still be served, because that is the whole reason
the proxy exists.
"""

import asyncio
import os
from dataclasses import replace
from pathlib import Path

import pytest

from conflux import config, tiles


def _settings(monkeypatch, **overrides):
    """Settings is frozen, so swap in a modified copy for the test."""
    monkeypatch.setattr(config, "SETTINGS", replace(config.SETTINGS, **overrides))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Point the tile settings at a temp dir and reset module state."""
    _settings(monkeypatch, tile_cache_dir=str(tmp_path))
    monkeypatch.setattr(tiles, "_cache_disabled", False)
    monkeypatch.setattr(tiles, "_writes_since_prune", 0)
    return tmp_path


# --- coordinate validation ---

@pytest.mark.parametrize("z,x,y", [(0, 0, 0), (1, 1, 1), (10, 512, 300), (19, 0, 524287)])
def test_valid_tiles_accepted(z, x, y):
    assert tiles.is_valid_tile(z, x, y)


@pytest.mark.parametrize("z,x,y", [
    (-1, 0, 0),      # negative zoom
    (20, 0, 0),      # past max zoom
    (1, 2, 0),       # x outside the pyramid at this zoom
    (1, 0, 2),       # y outside the pyramid at this zoom
    (10, -1, 0),     # negative index
])
def test_invalid_tiles_rejected(z, x, y):
    assert not tiles.is_valid_tile(z, x, y)


def test_cache_path_is_z_x_y():
    assert tiles.cache_path(Path("/c"), 12, 34, 56) == Path("/c/12/34/56.png")


def test_upstream_url_substitutes_all_placeholders():
    url = tiles.upstream_url("https://t/{z}/{x}/{y}.png", 3, 4, 5)
    assert url == "https://t/3/4/5.png"


# --- expiry ---

def test_missing_tile_is_not_fresh(cache):
    assert not tiles.is_fresh(cache / "nope.png", 30)


def test_old_tile_is_stale_and_recent_one_is_fresh(cache):
    path = cache / "t.png"
    path.write_bytes(b"x")
    old = path.stat().st_mtime - 40 * 86400
    os.utime(path, (old, old))
    assert not tiles.is_fresh(path, 30)
    assert tiles.is_fresh(path, 60)


def test_zero_max_age_means_cache_never_expires(cache):
    path = cache / "t.png"
    path.write_bytes(b"x")
    os.utime(path, (0, 0))
    assert tiles.is_fresh(path, 0)


# --- eviction ---

def test_prune_evicts_oldest_until_under_cap(cache):
    for i in range(5):
        p = cache / "10" / str(i) / "0.png"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"0" * 100)
        os.utime(p, (1_000 + i, 1_000 + i))  # ascending mtime: 0 is oldest

    removed = tiles.prune(cache, 250)  # room for two 100-byte tiles

    assert removed == 3
    survivors = sorted(p.parent.name for p in cache.rglob("*.png"))
    assert survivors == ["3", "4"]


def test_prune_is_a_noop_under_the_cap(cache):
    p = cache / "1" / "1" / "1.png"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"0" * 10)
    assert tiles.prune(cache, 1e6) == 0
    assert p.exists()


def test_prune_disabled_by_nonpositive_cap(cache):
    p = cache / "1" / "1" / "1.png"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"0" * 10)
    assert tiles.prune(cache, 0) == 0
    assert p.exists()


# --- fetch / cache / offline fallback ---

def test_fetch_caches_then_serves_from_disk_without_refetching(cache):
    calls = []

    def fake_fetch(z, x, y):
        calls.append((z, x, y))
        return b"PNGDATA"

    assert asyncio.run(tiles.get_tile(3, 1, 2, fetch=fake_fetch)) == b"PNGDATA"
    assert tiles.cache_path(cache, 3, 1, 2).read_bytes() == b"PNGDATA"

    # second request is a cache hit: upstream is not touched again
    assert asyncio.run(tiles.get_tile(3, 1, 2, fetch=fake_fetch)) == b"PNGDATA"
    assert calls == [(3, 1, 2)]


def test_stale_tile_is_served_when_upstream_is_down(cache):
    """The point of the proxy: no internet still draws already-seen areas."""
    path = tiles.cache_path(cache, 5, 6, 7)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"OLDTILE")
    old = path.stat().st_mtime - 999 * 86400
    os.utime(path, (old, old))  # far past any expiry

    def dead_upstream(z, x, y):
        raise OSError("network is unreachable")

    assert asyncio.run(tiles.get_tile(5, 6, 7, fetch=dead_upstream)) == b"OLDTILE"


def test_uncached_tile_with_upstream_down_returns_none(cache):
    def dead_upstream(z, x, y):
        raise OSError("network is unreachable")

    assert asyncio.run(tiles.get_tile(5, 6, 8, fetch=dead_upstream)) is None


def test_upstream_disabled_serves_cache_only(cache, monkeypatch):
    _settings(monkeypatch, tile_cache_dir=str(cache), tile_upstream_enabled=False)

    def unexpected(z, x, y):  # pragma: no cover - must never run
        raise AssertionError("upstream called while disabled")

    assert asyncio.run(tiles.get_tile(2, 1, 1, fetch=unexpected)) is None


def test_unwritable_cache_degrades_to_proxy_only(cache, monkeypatch):
    _settings(monkeypatch, tile_cache_dir="/proc/definitely/not/writable")
    assert asyncio.run(tiles.get_tile(4, 2, 3, fetch=lambda z, x, y: b"PNG")) == b"PNG"
    assert tiles._cache_disabled is True
