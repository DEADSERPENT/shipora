"""Benchmark of the local voice stack on the machine it runs on (real models, nothing mocked except the database).

    cd backend-fastapi
    .venv/Scripts/python.exe scripts/benchmark_voice.py [--json out.json]     (optional: pip install psutil for peak RAM)

Test audio is SYNTHETIC: English sentences spoken by Kokoro (two voices), then white noise added at fixed SNRs. That measures
robustness to noise, not to accents, microphones or real human speech — treat WER as a relative number, not a field figure.
Warm the Ollama model first (first load can take >30 s). All numbers come from one run under identical conditions."""

import argparse
import asyncio
import io
import json
import os
import re
import statistics as st
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/shipora-bench"   # in-memory DB, whatever .env says
os.environ.setdefault("JWT_SECRET", "Bench-Only-Secret-0f9aKd7LmXc2RhE8yBw5NpJsVq3Z")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from beanie import init_beanie  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import config  # noqa: E402
from database import DOCUMENT_MODELS  # noqa: E402
from models.customer import Customer, Location  # noqa: E402
from models.delivery_issue import DeliveryIssue  # noqa: E402
from models.shipment import ParcelDetails, Party, Shipment  # noqa: E402
from services import stt, tts  # noqa: E402
from models.shipment import generate_tracking_number  # noqa: E402
from voice.transcript_fix import fix_transcript  # noqa: E402

VOICES = ["af_heart", "am_michael"]
SNRS = [None, 20, 10, 5]   # dB; None = clean
SENTENCES = [
    "Where is my parcel?", "How long will my delivery take?", "I want to report a damaged package.",
    "Can you tell me the price for sending five kilograms across the city?", "The rider has not arrived yet.",
    "Please cancel my pickup for tomorrow morning.", "My parcel was delivered to the wrong address.",
    "What time does the delivery agent come today?", "I need to change the delivery address.",
    "Is my package out for delivery?", "How do I contact the support team?", "The tracking page shows no updates since yesterday.",
]

def say(text=""):
    sys.stdout.write(str(text) + chr(10))


def vram_mb() -> int:
    return int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]).decode().split()[0])


class VramPeak:
    def __enter__(self):
        self.peak, self._stop = vram_mb(), threading.Event()
        def poll():
            while not self._stop.wait(0.25):
                self.peak = max(self.peak, vram_mb())
        self._t = threading.Thread(target=poll, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set(), self._t.join()


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """(word errors, reference words), punctuation- and case-insensitive."""
    norm = lambda s: re.findall(r"[a-z0-9']+", s.lower())
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)], len(r)


def synth(pipeline, text: str, voice: str) -> np.ndarray:
    path = tts._kokoro_files(voice)["voice"]
    return np.concatenate(tts._kokoro_run(pipeline, path, text))


def with_noise(x: np.ndarray, snr_db, rng) -> np.ndarray:
    if snr_db is None:
        return x
    noise = rng.standard_normal(len(x)).astype(np.float32)
    noise *= np.sqrt(np.mean(x ** 2) / (10 ** (snr_db / 10)) / np.mean(noise ** 2))
    return np.clip(x + noise, -1, 1)


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "n/a"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    rng, report = np.random.default_rng(7), {}
    try:
        import psutil
        proc = psutil.Process()
    except ImportError:
        proc = None

    say(f"STT={config.STT_PROVIDER} ({config.FASTER_WHISPER_MODEL}, beam {config.FASTER_WHISPER_BEAM_SIZE})  TTS={config.TTS_PROVIDER} ({config.KOKORO_DEVICE})  LLM={config.OLLAMA_MODEL}")
    base_vram = vram_mb()
    say(f"GPU memory in use before loading: {base_vram} MiB")
    with VramPeak() as vp:
        stt._load_whisper_model(); tts._load_kokoro()
    pipeline = tts._kokoro_state[0]
    say(f"Models loaded on: STT={stt._whisper_model.model.device}  TTS={tts._kokoro_state[1]}   GPU peak while loading {vp.peak} MiB")

    # ── TTS: latency + real-time factor ─────────────────────────────────────
    tts_ms, tts_rtf, clips = [], [], []
    ids = [generate_tracking_number() for _ in range(6)]
    items = [(s, s, v) for s in SENTENCES for v in VOICES] + [(f"Where is my parcel {i}?", f"where is my parcel S H P {' '.join(i[3:])}", v) for i in ids for v in VOICES]
    with VramPeak() as vp_tts:
        for ref, spoken, voice in items:
            t = time.perf_counter(); wav = synth(pipeline, spoken, voice); dt = time.perf_counter() - t
            tts_ms.append(dt * 1000); tts_rtf.append(dt / (len(wav) / 24000)); clips.append((ref, wav, ref != spoken and ref))
    report["tts"] = {"clips": len(items), "median_ms": round(st.median(tts_ms)), "p95_ms": round(sorted(tts_ms)[int(.95 * len(tts_ms)) - 1]), "median_rtf": round(st.median(tts_rtf), 3), "gpu_peak_mib": vp_tts.peak}

    # ── STT: accuracy by noise level + latency ──────────────────────────────
    stt_rows = {}
    stt_ms, stt_rtf = [], []
    with VramPeak() as vp_stt:
        for snr in SNRS:
            errs = words = id_ok = id_n = 0
            for ref, wav, is_id in clips:
                audio = tts.encode_wav_pcm16(with_noise(wav, snr, rng), 24000)
                t = time.perf_counter(); heard = tts_text = stt.FasterWhisperProvider().transcribe(audio, "x.wav") or ""; dt = time.perf_counter() - t
                stt_ms.append(dt * 1000); stt_rtf.append(dt / (len(wav) / 24000))
                if is_id:   # tracking-number exact match, after the same repair the pipeline applies
                    id_n += 1; id_ok += ref.split()[-1].rstrip("?") in re.sub(r"[^A-Za-z0-9]", "", fix_transcript(heard).upper())
                else:
                    e, n = wer(ref, heard); errs += e; words += n
            stt_rows["clean" if snr is None else f"{snr} dB SNR"] = {"WER": pct(errs, words), "tracking_id_exact": f"{id_ok}/{id_n}"}
    report["stt"] = {"by_noise": stt_rows, "median_ms": round(st.median(stt_ms)), "p95_ms": round(sorted(stt_ms)[int(.95 * len(stt_ms)) - 1]),
                     "median_rtf": round(st.median(stt_rtf), 3), "gpu_peak_mib": vp_stt.peak}

    # ── LLM + tools: agent routing, grounding, confirmation, latency ────────
    await init_beanie(database=AsyncMongoMockClient()["bench"], document_models=DOCUMENT_MODELS)
    cust = Customer(name="Bench Cust", email="b@bench.test", password="x", phone="9880000010", address="1 Test St", location=Location(lat=12.93, lng=77.62))
    await cust.insert()
    tn = generate_tracking_number()
    ship = Shipment(trackingNumber=tn, customerId=cust.id, customerName=cust.name,
                    sender=Party(name="S", phone="9880000099", address="Sender Rd", location=Location(lat=12.93, lng=77.62)),
                    recipient=Party(name="R", phone="9770000077", address="Drop Rd", location=Location(lat=12.97, lng=77.64)),
                    parcel=ParcelDetails(), status="OUT_FOR_DELIVERY")
    ship.record("OUT_FOR_DELIVERY", "admin")
    await ship.insert()
    user = {"id": str(cust.id), "role": "user", "name": cust.name}
    from agents.orchestrator import route_and_reply
    cases = [  # (message, accepted agents, reply must contain)
        (f"Where is my parcel {tn}?", {"tracking"}, [tn]), (f"What is the status of {tn}", {"tracking"}, [tn]),
        (f"track {tn} please", {"tracking"}, [tn]), (f"Is {tn} out for delivery?", {"tracking"}, ["out for delivery"]),
        (f"My parcel {tn} arrived damaged and I want to file a complaint", {"complaints"}, []),
        ("How much does it cost to send a parcel?", {"support", "general"}, []), ("Hello", {"general", "support"}, []),
    ]
    rows, lat = [], []
    for msg, agents, needles in cases:
        t = time.perf_counter(); res = await route_and_reply(msg, [], user, session_id=f"bench-{len(rows)}"); dt = (time.perf_counter() - t) * 1000
        lat.append(dt)
        rows.append({"message": msg[:48], "agent": res["agent"], "source": res["source"], "routed_ok": res["agent"] in agents,
                     "grounded_ok": all(n.lower() in res["reply"].lower() for n in needles), "ms": round(dt)})
    filed = await DeliveryIssue.find_all().count()   # a complaint must wait for confirmation: nothing filed by a single turn
    report["llm_agents"] = {"model": config.OLLAMA_MODEL, "cases": rows, "routed_ok": sum(r["routed_ok"] for r in rows), "grounded_ok": sum(r["grounded_ok"] for r in rows),
                            "n": len(rows), "median_total_ms": round(st.median(lat)), "complaints_filed_without_confirmation": filed,
                            "sources": sorted({r["source"] for r in rows})}

    # First-token latency straight from Ollama (streaming), same model/ctx as the app.
    import httpx
    ftl, tot = [], []
    with httpx.Client(timeout=120) as http:
        for _ in range(5):
            t = time.perf_counter(); first = None
            with http.stream("POST", f"{config.OLLAMA_URL}/api/chat", json={"model": config.OLLAMA_MODEL, "stream": True, "keep_alive": config.OLLAMA_KEEP_ALIVE,
                             "options": {"num_ctx": config.OLLAMA_NUM_CTX}, "messages": [{"role": "user", "content": "In one sentence, what does a delivery tracking number do?"}]}) as r:
                for line in r.iter_lines():
                    if line and first is None and json.loads(line).get("message", {}).get("content"):
                        first = (time.perf_counter() - t) * 1000
            ftl.append(first); tot.append((time.perf_counter() - t) * 1000)
    report["ollama_stream"] = {"median_first_token_ms": round(st.median(ftl)), "median_total_ms": round(st.median(tot))}

    report["memory"] = {"peak_ram_mib": round(proc.memory_info().peak_wset / 2**20) if proc and hasattr(proc.memory_info(), "peak_wset") else None,
                        "gpu_before_mib": base_vram, "gpu_peak_with_ollama_mib": vram_mb()}
    say(json.dumps(report, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
