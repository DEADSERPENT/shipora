"""Verifies the voice "sandwich" (STT -> LLM/agents -> TTS) stage by stage with the REAL configured providers, then as
one round trip through POST /api/voice/chat. Uses an in-memory database seeded with one known shipment, so the answer can
be checked against ground truth rather than eyeballed.

    cd backend-fastapi
    .venv/Scripts/python.exe scripts/verify_sandwich.py [--json report.json]

Stage 1  TTS      speak a known sentence (synthetic "caller")        -> audio bytes, valid WAV/MP3
Stage 2  STT      transcribe that audio                              -> transcript; word-overlap with what was said
Stage 3  Agents   route + answer the transcript against the DB       -> reply must contain the shipment's true status
Stage 4  TTS      speak the reply                                    -> audio bytes
Stage 5  Round trip  upload the stage-1 audio to /api/voice/chat     -> same checks end to end + latency budget

Exit code 1 if any stage fails. Providers come from .env (STT_PROVIDER / TTS_PROVIDER); the database is never real."""

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/shipora-verify"   # force the in-memory DB, whatever .env says
os.environ.setdefault("JWT_SECRET", "Verify-Only-Secret-0f9aKd7LmXc2RhE8yBw5NpJsVq3Z")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from beanie import init_beanie  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import config  # noqa: E402
from database import DOCUMENT_MODELS  # noqa: E402
from models.customer import Customer, Location  # noqa: E402
from models.shipment import ParcelDetails, Party, Shipment, generate_tracking_number  # noqa: E402
from services.stt import transcribe_audio  # noqa: E402
from services.tts import audio_mime_type, synthesize_speech  # noqa: E402

LATENCY_BUDGET_MS = {"stt": 8000, "llm": 15000, "tts": 8000}   # generous: allows CPU-only machines


def execution_note() -> str:
    """Where the configured models actually run, so the latency line is not misread."""
    if config.STT_PROVIDER == "faster_whisper":
        stt_where = "CPU" if config.FASTER_WHISPER_DEVICE == "cpu" else "GPU if CUDA works, else CPU"
    elif config.STT_PROVIDER == "openai":
        stt_where = "cloud"
    else:
        stt_where = config.ONNX_STT_DEVICE.upper()
    llm_where = f"Ollama {config.OLLAMA_MODEL} (GPU if the model fits in VRAM)"
    tts_where = "cloud" if config.TTS_PROVIDER == "openai" else "CPU"
    return f"STT {stt_where}; LLM {llm_where}; TTS {tts_where}"


def say(text=""):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def overlap(said, heard):
    s, h = words(said), set(words(heard))
    return sum(1 for w in s if w in h) / len(s) if s else 0.0


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    stages, results = [], {}

    def record(name, ok, detail, ms=None):
        stages.append({"stage": name, "ok": bool(ok), "detail": detail, "ms": ms})
        say(f"{'PASS' if ok else 'FAIL'}  {name:<34} {f'{ms:>6} ms  ' if ms is not None else '           '}{detail}")

    say(f"Providers: STT={config.STT_PROVIDER}  TTS={config.TTS_PROVIDER}  LLM=ollama/{config.OLLAMA_MODEL}  router={config.CLASSIFIER_MODE}\n")

    await init_beanie(database=AsyncMongoMockClient()["verify"], document_models=DOCUMENT_MODELS)
    cust = Customer(name="Verify Cust", email="v@verify.test", password="x", phone="9880000010", address="1 Test St",
                    location=Location(lat=12.93, lng=77.62))
    await cust.insert()
    TN = generate_tracking_number()
    ship = Shipment(trackingNumber=TN, customerId=cust.id, customerName=cust.name,
                    sender=Party(name="S", phone="9880000099", address="Sender Rd", location=Location(lat=12.93, lng=77.62)),
                    recipient=Party(name="R", phone="9770000077", address="Drop Rd", location=Location(lat=12.97, lng=77.64)),
                    parcel=ParcelDetails(), status="OUT_FOR_DELIVERY")
    ship.record("OUT_FOR_DELIVERY", "admin")
    await ship.insert()

    said = "Where is my parcel? The tracking number is S H P " + " ".join(TN[3:]) + "."
    # Stage 1 — TTS as the synthetic caller
    t = time.perf_counter()
    caller_audio = await synthesize_speech(said)
    ms = int((time.perf_counter() - t) * 1000)
    record("1 TTS (caller audio)", bool(caller_audio) and len(caller_audio) > 2000,
           f"{len(caller_audio or b'')} bytes, {audio_mime_type(caller_audio) if caller_audio else 'none'}", ms)
    if not caller_audio:
        say("\nNo audio from TTS — nothing downstream can be tested. Check TTS_PROVIDER / local_models/piper.")
        return 1

    # Stage 2 — STT
    t = time.perf_counter()
    transcript = await transcribe_audio(caller_audio, "caller.wav")
    ms = int((time.perf_counter() - t) * 1000)
    score = overlap("where is my parcel the tracking number is", transcript or "")
    record("2 STT (transcribe)", bool(transcript) and score >= 0.6, f"heard: {transcript!r}  word-overlap {score:.0%}", ms)
    results["transcript"] = transcript
    heard_tracking = TN in re.sub(r"[^A-Za-z0-9]", "", (transcript or "").upper())
    say(f"NOTE  2b spelled tracking number {'recognised exactly' if heard_tracking else 'MIS-HEARD by STT (expected for spelled IDs) — stage 5c checks the pipeline recovers'}")

    # Stage 3 — agents against DB truth (feed ground-truth text so a STT miss in 2b doesn't mask an agent bug)
    from agents.orchestrator import route_and_reply
    t = time.perf_counter()
    res = await route_and_reply(f"Where is my parcel {TN}?", [], None)
    ms = int((time.perf_counter() - t) * 1000)
    grounded = bool(re.search(r"out for delivery", res["reply"], re.I))
    record("3 Agents (grounded in DB)", res["agent"] == "tracking" and grounded,
           f"agent={res['agent']} source={res['source']} reply={res['reply'][:90]!r}", ms)

    # Stage 4 — TTS of the reply
    t = time.perf_counter()
    reply_audio = await synthesize_speech(res["reply"])
    ms = int((time.perf_counter() - t) * 1000)
    record("4 TTS (reply audio)", bool(reply_audio) and len(reply_audio) > 2000, f"{len(reply_audio or b'')} bytes", ms)

    # Stage 5 — the whole sandwich over HTTP
    from main import api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://v", timeout=120) as http:
        t = time.perf_counter()
        from auth_utils import sign_token
        auth = {"Authorization": f"Bearer {sign_token({'id': str(cust.id), 'role': 'user'})}"}   # the caller is the shipment's owner
        r = await http.post("/api/voice/chat", headers=auth, files={"audio": ("caller.wav", caller_audio, "audio/wav")}, data={"sessionId": "verify-1", "speak": "true"})
        wall = int((time.perf_counter() - t) * 1000)
    ok_http = r.status_code == 200
    body = r.json() if ok_http else {}
    lat = body.get("latencyMs") or {}
    out_audio = base64.b64decode(body["audioBase64"]) if body.get("audioBase64") else b""
    record("5 Round trip /api/voice/chat", ok_http and bool(out_audio) and bool(body.get("reply")),
           f"HTTP {r.status_code} agent={body.get('agent')} source={body.get('source')} reply={str(body.get('reply'))[:70]!r}", wall)
    if lat:
        within = all(lat.get(k) is None or lat[k] <= v for k, v in LATENCY_BUDGET_MS.items())
        record("5b Latency within budget", within, f"stt={lat.get('stt')} llm={lat.get('llm')} tts={lat.get('tts')} total={lat.get('total')} ms "
               f"(budget {LATENCY_BUDGET_MS}; {execution_note()} — production telephony targets are far lower)")
    reply = str(body.get("reply", ""))
    recovered = bool(re.search(r"out for delivery", reply, re.I)) or TN in reply
    record("5c Spoken-ID resilience", recovered, "reply names the right parcel (exact match or 'did you mean' repair)" if recovered
           else f"expected {TN}, STT heard {re.findall(r'[A-Za-z]*[0-9]{6,}', (body.get('transcript') or ''))}; reply: {reply[:70]!r}")
    results["roundtrip"] = body and {k: body[k] for k in ("reply", "agent", "source", "transcript", "latencyMs")}

    failed = [s["stage"] for s in stages if not s["ok"]]
    say("\n" + ("SANDWICH OK: every stage passed." if not failed else "FAILED stages: " + ", ".join(failed)))
    if args.json:
        Path(args.json).write_text(json.dumps({"stages": stages, **results}, indent=2, default=str), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
