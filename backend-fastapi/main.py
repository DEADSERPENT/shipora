import asyncio
import logging
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Windows terminals default stdout to cp1252, which can't encode the emoji
# in startup log messages (connect_db, sockets) and crashes the process.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import logging_config
from auth_utils import verify_token
import database
from database import connect_db
from seed import seed_mock_data
from routes.admin import router as admin_router
from routes.analytics import router as analytics_router
from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.complaints import router as complaints_router
from routes.shipments import router as shipments_router
from routes.support import router as support_router
from routes.vehicles import router as vehicles_router
from routes.voice import router as voice_router
from voice import warmup
from services import dispatch, simulator
from sockets import sio, sweep_stale_forever

logging_config.setup_logging()
log = logging.getLogger("shipora.http")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging_config.setup_logging()
    config.validate()  # refuse to start on a missing/insecure JWT_SECRET, bad CORS origins, unknown APP_ENV
    await connect_db()
    if database.IN_MEMORY:  # never put demo rows into a real (Atlas/local) database
        await seed_mock_data()
    warm = asyncio.create_task(warmup.warm_up()) if config.VOICE_WARMUP else None   # background: never delays startup
    sweeper = asyncio.create_task(sweep_stale_forever())  # flips silent vehicles to "stale" and tells watchers
    dispatcher = asyncio.create_task(dispatch.sweep_forever()) if config.auto_assign_enabled() else None   # matches waiting shipments to agents
    simulator_task = asyncio.create_task(simulator.run_forever()) if config.simulation_enabled(database.IN_MEMORY) else None   # simulated riders
    try:
        yield
    finally:
        sweeper.cancel()
        for task in (warm, dispatcher, simulator_task):
            if task:
                task.cancel()


api = FastAPI(
    title="Shipora API",
    description="Shipora — Parcel Delivery & Fleet Management Platform — FastAPI backend",
    lifespan=lifespan,
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.middleware("http")
async def request_logging(request: Request, call_next):
    """One structured access line per request (method, path, status, latency, caller), a correlation id that is
    also returned as X-Request-ID, and a safe JSON body for anything that escapes the route handlers."""
    incoming = request.headers.get("x-request-id", "")
    rid = incoming if _REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
    token = logging_config.request_id_var.set(rid)
    started = time.perf_counter()
    caller = {}
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            claims = verify_token(auth.split(" ", 1)[1])
            caller = {"user_id": claims.get("id"), "role": claims.get("role")}
        except Exception:
            pass
    try:
        try:
            response = await call_next(request)
        except Exception as err:
            log.exception("unhandled error", extra={"event": "unhandled_error", "method": request.method, "path": request.url.path,
                                                    "error_type": type(err).__name__, **caller})
            response = JSONResponse(status_code=500, content={"message": "Internal server error", "requestId": rid})
        response.headers["X-Request-ID"] = rid
        status = response.status_code
        level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.DEBUG if request.url.path == "/api/health" else logging.INFO
        log.log(level, "request", extra={"event": "http_request", "method": request.method, "path": request.url.path, "status": status,
                                         "latency_ms": round((time.perf_counter() - started) * 1000, 1), **caller})
        return response
    finally:
        logging_config.request_id_var.reset(token)


@api.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    """Frontend reads err.response?.data?.message everywhere — remap FastAPI's
    default {"detail": ...} envelope to {"message": ...} to match server.js."""
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail}, headers=getattr(exc, "headers", None))


@api.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    """Keeps the {"message": ...} envelope the frontend reads for validation failures too,
    with a readable first error and the field-level list. Rejected input values are never echoed."""
    errors = [{"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")), "message": e["msg"]} for e in exc.errors()]
    first = errors[0] if errors else {"field": "", "message": "Invalid request"}
    text = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
    return JSONResponse(status_code=422, content={"message": text, "errors": errors})


api.include_router(auth_router)
api.include_router(vehicles_router)
api.include_router(shipments_router)
api.include_router(admin_router)
api.include_router(complaints_router)
api.include_router(support_router)
api.include_router(chat_router)
api.include_router(voice_router)
api.include_router(analytics_router)


@api.get("/api/health", tags=["Health"], summary="Health check")
async def health():
    return {"status": "OK", "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")}


@api.get("/api/health/ready", tags=["Health"], summary="Readiness: can this instance serve traffic (database reachable)?")
async def ready():
    """Liveness is /api/health (process is up). Readiness additionally proves the database answers, and reports
    503 while not ready."""
    from models.shipment import Shipment
    try:
        await Shipment.get_motor_collection().find_one({}, {"_id": 1})
    except Exception as err:
        log.error("readiness check failed", extra={"event": "not_ready", "error_type": type(err).__name__})
        return JSONResponse(status_code=503, content={"status": "NOT_READY", "database": "unreachable"})
    return {"status": "READY", "environment": config.app_env(), "database": "in-memory" if database.IN_MEMORY else "mongodb"}


# Combined ASGI app: Socket.IO events + FastAPI HTTP routes side by side,
# mirrors server.js wiring Socket.IO onto the same http.Server as Express.
app = socketio.ASGIApp(sio, other_asgi_app=api)
