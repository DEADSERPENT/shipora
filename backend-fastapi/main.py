import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Windows terminals default stdout to cp1252, which can't encode the emoji
# in startup log messages (connect_db, sockets) and crashes the process.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from database import connect_db
from seed import seed_mock_data
from routes.admin import router as admin_router
from routes.analytics import router as analytics_router
from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.complaints import router as complaints_router
from routes.support import router as support_router
from routes.vehicles import router as vehicles_router
from routes.voice import router as voice_router
from sockets import sio


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await connect_db()
    await seed_mock_data()
    yield


api = FastAPI(
    title="EcoTrack API",
    description="Waste Disposal Management System — FastAPI backend",
    lifespan=lifespan,
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=[config.CLIENT_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    """Frontend reads err.response?.data?.message everywhere — remap FastAPI's
    default {"detail": ...} envelope to {"message": ...} to match server.js."""
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})


api.include_router(auth_router)
api.include_router(vehicles_router)
api.include_router(admin_router)
api.include_router(complaints_router)
api.include_router(support_router)
api.include_router(chat_router)
api.include_router(voice_router)
api.include_router(analytics_router)


@api.get("/api/health", tags=["Health"], summary="Health check")
async def health():
    return {"status": "OK", "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")}


# Combined ASGI app: Socket.IO events + FastAPI HTTP routes side by side,
# mirrors server.js wiring Socket.IO onto the same http.Server as Express.
app = socketio.ASGIApp(sio, other_asgi_app=api)
