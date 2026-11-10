"""ClaimGuard API entry point. Run: uvicorn app.main:app --reload (from backend/)."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import ROOT, settings
from app.database import db as database
from app.models import models as m
from app.services.events import bus


@asynccontextmanager
async def lifespan(app):
    database.init_db()
    s = database.SessionLocal()
    try:
        if s.query(m.Claim).count() == 0:
            from app.simulation.benchmark import load_demo
            load_demo(s, 42)
    finally:
        s.close()
    yield


app = FastAPI(title="ClaimGuard", version="1.0.0", lifespan=lifespan,
              description="Autonomous multi-agent healthcare claim prevention system (synthetic data only).")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.websocket("/ws/claimguard")
async def ws(socket: WebSocket):
    await socket.accept()
    q = bus.subscribe()
    try:
        await socket.send_json({"type": "hello", "agent_status": list(bus.agent_status.values()),
                                "recent": list(bus.recent)[-100:]})
        while True:
            batch = [await q.get()]
            while not q.empty() and len(batch) < 200:
                batch.append(q.get_nowait())
            await socket.send_json({"type": "batch", "events": batch})
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)


# Serve the built frontend when present (single-process local demo).
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() and Path(f).resolve().is_relative_to(DIST.resolve()) else DIST / "index.html")
