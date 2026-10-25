"""HTTP + WebSocket API for the Studio UI. Every route calls commands.py, the same layer the MCP server uses.

Run:  python -m novastudio serve     (binds 127.0.0.1 only)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import Body, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import commands as C
from .config import RESOURCES, STUDIO_ROOT, workspace
from .i18n import lang_of
from .store import StudioError

app = FastAPI(title="NovaSolver Studio", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(StudioError)
async def _studio_error(request, exc: StudioError):
    lang = lang_of(request.query_params.get("lang"))
    return JSONResponse(C.error_payload(exc, lang), status_code=exc.status)


@app.exception_handler(Exception)
async def _unexpected(request, exc: Exception):
    # never send a Python traceback to the UI; the first line is enough and the server log keeps the rest
    import logging
    logging.getLogger("novastudio").exception("unexpected error")
    return JSONResponse({"error": "err.internal", "message": f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"},
                        status_code=500)


def call(fn, *a, **kw):
    return run_in_threadpool(fn, *a, **kw)


@app.get("/api/env")
async def env(lang: str = "ja"):
    return await call(C.environment_check, lang)


@app.get("/api/templates")
async def templates_(lang: str = "ja"):
    return await call(C.list_templates, lang)


@app.get("/api/cases")
async def cases():
    return await call(C.list_cases)


@app.post("/api/cases")
async def create(body: dict = Body(...), lang: str = "ja"):
    return await call(C.create_case, body["template"], body.get("params"), lang)


@app.post("/api/import")
async def import_cad(request: Request, physics: str = "structural", filename: str = Query(...), lang: str = "ja"):
    """Raw file bytes in the body (no multipart dependency). Example: POST /api/import?physics=thermal&filename=a.step"""
    data = await request.body()
    return await call(C.import_geometry, physics, filename, data, None, lang)


@app.get("/api/samples")
async def samples(lang: str = "ja"):
    return await call(C.list_samples, lang)


@app.post("/api/samples/{name}")
async def open_sample(name: str, physics: str | None = None, lang: str = "ja"):
    return await call(C.open_sample, name, physics, lang)


@app.get("/api/cases/{case_id}")
async def get_case(case_id: str, lang: str = "ja"):
    return await call(C.case_payload, case_id, lang)


@app.patch("/api/cases/{case_id}")
async def patch_case(case_id: str, body: dict = Body(...), lang: str = "ja"):
    return await call(C.update_case, case_id, body["expected_revision"], body["changes"], lang)


@app.delete("/api/cases/{case_id}")
async def delete_case(case_id: str, confirm: str = Query(...), lang: str = "ja"):
    return await call(C.delete_case, case_id, confirm, lang)


@app.get("/api/cases/{case_id}/geometry")
async def geometry(case_id: str, lang: str = "ja"):
    return await call(C.geometry_payload, case_id, lang)


@app.get("/api/cases/{case_id}/validate")
async def validate(case_id: str, lang: str = "ja"):
    return await call(C.validate_case, case_id, lang)


@app.post("/api/cases/{case_id}/mesh")
async def mesh(case_id: str, body: dict = Body(default={}), lang: str = "ja"):
    return await call(C.generate_mesh, case_id, (body or {}).get("size"), lang)


@app.post("/api/cases/{case_id}/run")
async def run(case_id: str, body: dict = Body(default={}), lang: str = "ja"):
    r = await call(C.run_simulation, case_id, (body or {}).get("mode"), 0.0, lang)
    return {"job_id": r["job"]["job_id"], "job": r["job"]} if not r["done"] else r


@app.post("/api/cases/{case_id}/convergence")
async def convergence(case_id: str, lang: str = "ja"):
    r = await call(C.check_convergence, case_id, 0.0, lang)
    return {"job_id": r["job"]["job_id"], "job": r["job"]} if not r["done"] else r


@app.get("/api/jobs/{job_id}")
async def job(job_id: str, lang: str = "ja"):
    return await call(C.job_status, job_id, lang)


@app.post("/api/jobs/{job_id}/stop")
async def stop(job_id: str, lang: str = "ja"):
    return await call(C.stop_job, job_id, lang)


@app.get("/api/cases/{case_id}/results")
async def results_(case_id: str, run_id: str | None = None, lang: str = "ja"):
    return await call(C.get_results, case_id, run_id, lang)


@app.get("/api/cases/{case_id}/verify")
async def verify(case_id: str, lang: str = "ja"):
    return await call(C.verify_case, case_id, lang)


@app.get("/api/cases/{case_id}/field")
async def field(case_id: str, quantity: str = "", lang: str = "ja"):
    return await call(C.field, case_id, quantity, lang)


@app.get("/api/cases/{case_id}/render.png")
async def render(case_id: str, quantity: str = "", lang: str = "ja"):
    png, _ = await call(C.render_view, case_id, quantity, lang)
    return Response(png, media_type="image/png")


# ------------------------------------------------------------------ live updates

class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.seen: dict[str, float] = {}
        self.task: asyncio.Task | None = None

    async def loop(self):
        root = workspace() / "cases"
        while True:
            try:
                msgs = []
                for f in root.glob("c_*/case.json"):
                    m = f.stat().st_mtime
                    if self.seen.get(str(f)) != m:
                        first = str(f) not in self.seen
                        self.seen[str(f)] = m
                        if not first:
                            c = json.loads(f.read_text(encoding="utf-8"))
                            msgs.append({"type": "case", "case_id": c["case_id"], "revision": c["revision"]})
                for f in root.glob("c_*/run/r_*/job.json"):
                    m = f.stat().st_mtime
                    if self.seen.get(str(f)) != m:
                        self.seen[str(f)] = m
                        j = json.loads(f.read_text(encoding="utf-8"))
                        if j["state"] in ("queued", "running") or __import__("time").time() - j["updated_at"] < 10:
                            msgs.append({"type": "job", "job": C.job_view(j, "en")})
                for msg in msgs:
                    for ws in list(self.clients):
                        try:
                            await ws.send_json(msg)
                        except Exception:
                            self.clients.discard(ws)
            except Exception:
                pass
            await asyncio.sleep(0.5)


hub = Hub()


@app.on_event("startup")
async def _start():
    hub.task = asyncio.create_task(hub.loop())


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    hub.clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.clients.discard(websocket)


# ------------------------------------------------------------------ the built UI (if present)

DIST = RESOURCES / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
