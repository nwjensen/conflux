"""Conflux application entrypoint.

Wires the FastAPI app, the read-only API, the Family Command Hub static UI, and
the two background loops (periodic tick + input simulator). State authority is
single and local; the loops only ever call the service layer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import app_state, config, db, service
from .adapters.simulator import get_simulator
from .api.routes import router
from .app_state import emit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("conflux")

HUB_DIR = Path(__file__).parent / "hub"


async def _tick_loop() -> None:
    """Periodic evaluation: absence escalation + scheduled SMS flush."""
    interval = config.SETTINGS.tick_interval
    while True:
        try:
            await asyncio.to_thread(service.tick_all)
        except Exception:  # a tick must never kill the loop
            log.exception("tick loop error")
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    service.ensure_seed_subjects()
    log.info("Conflux started (time_scale=%s, subjects=%s)",
             config.TIME_SCALE, service.active_subject_ids())

    tasks = [asyncio.create_task(_tick_loop())]
    if config.SETTINGS.simulator_enabled:
        sim = get_simulator()
        tasks.append(asyncio.create_task(sim.run(emit)))
        log.info("Input simulator running")
    if config.SETTINGS.aprs_enabled:
        from .adapters.aprs import APRSAdapter
        aprs = APRSAdapter()
        app_state.set_aprs_adapter(aprs)
        tasks.append(asyncio.create_task(aprs.run(emit)))
        log.info("APRS-IS adapter running (host=%s)", config.SETTINGS.aprs_host)

    try:
        yield
    finally:
        app_state.set_aprs_adapter(None)
        for t in tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Conflux", description="Guardian narrator — Phase 1", lifespan=lifespan)
app.include_router(router, prefix="/api")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(HUB_DIR / "index.html")


if (HUB_DIR / "app.js").exists():
    app.mount("/hub", StaticFiles(directory=str(HUB_DIR)), name="hub")
