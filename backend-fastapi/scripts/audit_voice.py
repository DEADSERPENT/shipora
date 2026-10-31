"""Speech-robustness audit with the REAL configured STT/TTS providers (no mocks, no database, no LLM).

    cd backend-fastapi
    .venv/Scripts/python.exe scripts/audit_voice.py [--json report.json]

Synthesises caller audio with Piper at different speaking speeds, mixes in white noise at set signal-to-noise ratios, then
runs STT (STT_PROVIDER from .env) + voice/transcript_fix.py and checks whether the tracking number survives. It also feeds
the STT stage the inputs that go wrong in production: empty, silent, noise-only, garbage bytes, truncated and over-long
recordings; and measures latency, concurrency and process memory.

What this cannot cover (there is no audio to test with): Indian-English or other accents (Piper only has the en_US voice
installed), and Hindi/Kannada (no Piper voice, no recordings). Those need real human recordings."""

import argparse
import asyncio
import io
import json
import os
import random
import sys
import time
import wave
from pathlib import Path

os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/shipora-audit"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import config  # noqa: E402
from services import stt, tts  # noqa: E402
from voice.transcript_fix import extract_id, fix_transcript  # noqa: E402


def say(text=""):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def rss_mb() -> float:
    """Resident memory of this process in MB (Windows via ctypes, elsewhere /proc)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb)
        return pmc.WorkingSetSize / 1048576
    with open("/proc/self/status") as f:
        return next(int(line.split()[1]) / 1024 for line in f if line.startswith("VmRSS"))


def piper_wav(text: str, length_scale: float = 1.0) -> bytes:
    """Caller audio at a given speaking speed (length_scale <1 faster, >1 slower)."""
    from piper import SynthesisConfig

    voice = tts._load_piper_voice()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=length_scale))
    return buf.getvalue()


def read_wav(data: bytes):
    with wave.open(io.BytesIO(data)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32), w.getframerate()


def write_wav(samples, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(samples, -32768, 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def with_noise(data: bytes, snr_db: float, seed: int = 7) -> bytes:
    samples, rate = read_wav(data)
    rms = float(np.sqrt(np.mean(samples ** 2))) or 1.0
    noise = np.random.default_rng(seed).normal(0, rms / (10 ** (snr_db / 20)), samples.shape)
    return write_wav(samples + noise, rate)


async def hear(audio: bytes):
    t = time.perf_counter()
    raw = await stt.transcribe_audio(audio, "caller.wav")
    ms = int((time.perf_counter() - t) * 1000)
    return raw, (fix_transcript(raw) if raw else raw), ms


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    rows, failures = [], []

    def record(group, name, ok, detail, ms=None):
        rows.append({"group": group, "case": name, "ok": bool(ok), "detail": detail, "ms": ms})
        if not ok:
            failures.append(name)
        say(f"{'PASS' if ok else 'FAIL'}  {group:<12} {name:<44} {f'{ms:>5} ms ' if ms is not None else '         '}{detail}")

    say(f"STT={config.STT_PROVIDER} (device={config.FASTER_WHISPER_DEVICE if config.STT_PROVIDER == 'faster_whisper' else config.ONNX_STT_DEVICE})  TTS={config.TTS_PROVIDER}\n")
    await hear(piper_wav("warm up"))        # model load is not part of what is being measured

    rng = random.Random(11)
    ids = [f"SHP{rng.randrange(10 ** 8):08d}" for _ in range(6)]

    # 1. speaking speed — ID spelled digit by digit, in a sentence
    for scale, label in ((0.7, "fast"), (1.0, "normal"), (1.4, "slow")):
        hits = 0
        for tn in ids:
            _, fixed, ms = await hear(piper_wav(f"Where is my parcel? The tracking number is S H P {' '.join(tn[3:])}.", scale))
            hits += extract_id(fixed or "") == tn
        record("speed", f"{label} speech (length_scale={scale}), {len(ids)} IDs", hits >= len(ids) - 1, f"{hits}/{len(ids)} IDs recovered exactly")

    # 2. background noise
    for snr in (20, 10, 5, 0):
        hits = 0
        for tn in ids:
            clean = piper_wav(f"Where is my parcel? The tracking number is S H P {' '.join(tn[3:])}.")
            _, fixed, ms = await hear(with_noise(clean, snr))
            hits += extract_id(fixed or "") == tn
        record("noise", f"white noise at {snr} dB SNR, {len(ids)} IDs", hits >= len(ids) - (1 if snr >= 10 else len(ids)), f"{hits}/{len(ids)} IDs recovered exactly" + ("  (informational below 10 dB)" if snr < 10 else ""))

    # 3. how an ID is spoken
    tn = ids[0]
    for label, sentence in (("digits grouped", f"Track {tn[:3]} {tn[3:7]} {tn[7:]}"),
                            ("digit by digit", f"Track S H P {' '.join(tn[3:])}"),
                            ("digit words", "Track S H P " + " ".join("zero one two three four five six seven eight nine".split()[int(c)] for c in tn[3:])),
                            ("legacy hex", "Track S H P 1 A 2 B 3 C 4 D 5 E")):
        _, fixed, ms = await hear(piper_wav(sentence))
        got = extract_id(fixed or "")
        want = "SHP1A2B3C4D5E" if label == "legacy hex" else tn
        record("spelling", label, got == want, f"heard {fixed!r} -> {got}", ms)

    # 4. inputs that go wrong in production — must never raise, and must never produce an invented transcript
    sr = 16000
    silence = write_wav(np.zeros(sr * 2), sr)
    noise_only = write_wav(np.random.default_rng(3).normal(0, 3000, sr * 3), sr)
    good = piper_wav("Where is my parcel? The tracking number is S H P 1 2 3 4 5 6 7 8.")
    for name, blob in (("empty bytes", b""), ("2 s of silence", silence), ("3 s of loud noise only", noise_only),
                       ("garbage bytes (not audio)", os.urandom(4096)), ("truncated mid-file (40%)", good[: int(len(good) * 0.4)]),
                       ("header only", good[:44])):
        try:
            raw, fixed, ms = await hear(blob)
            ok = not raw or extract_id(fixed or "") is None      # nothing heard, or at least no fabricated tracking number
            record("bad input", name, ok, f"transcript={raw!r}", ms)
        except Exception as err:
            record("bad input", name, False, f"RAISED {type(err).__name__}: {err}")

    # 5. long recording — the ONNX provider truncates at ONNX_STT_MAX_SECONDS; faster-whisper handles any length
    long_text = " ".join([f"Please check parcel S H P {' '.join(ids[i][3:])} for me." for i in range(6)] * 2)
    long_audio = piper_wav(long_text)
    secs = len(read_wav(long_audio)[0]) / read_wav(long_audio)[1]
    raw, fixed, ms = await hear(long_audio)
    found = {extract_id(m) for m in (fixed or "").split(".")} - {None}
    record("long", f"{secs:.0f} s recording", bool(raw) and ids[0] in (fixed or ""), f"{len(found)} distinct IDs heard; first ID {'present' if ids[0] in (fixed or '') else 'MISSING'}", ms)

    # 6. latency and memory over repeated turns, then concurrency
    clean = piper_wav(f"Where is my parcel? The tracking number is S H P {' '.join(ids[1][3:])}.")
    base = rss_mb()
    times = [(await hear(clean))[2] for _ in range(10)]
    record("latency", "STT, 10 sequential clips", True, f"median {sorted(times)[5]} ms, p90 {sorted(times)[8]} ms, max {max(times)} ms")
    spoken = "Your parcel SHP48217390 is out for delivery and should arrive today by 6 PM. The rider is Ravi, phone 98765 43210."
    t = [0] * 10
    for i in range(10):
        s = time.perf_counter()
        audio = await tts.synthesize_speech(spoken)
        t[i] = int((time.perf_counter() - s) * 1000)
    record("latency", "TTS, 10 sequential replies", bool(audio), f"median {sorted(t)[5]} ms, p90 {sorted(t)[8]} ms, max {max(t)} ms")
    record("memory", "growth over 20 calls", rss_mb() - base < 300, f"{base:.0f} MB -> {rss_mb():.0f} MB")
    for n in (4, 8):
        s = time.perf_counter()
        out = await asyncio.gather(*[hear(clean) for _ in range(n)])
        wall = int((time.perf_counter() - s) * 1000)
        ok = all(extract_id(o[1] or "") == ids[1] for o in out)
        record("concurrency", f"{n} simultaneous STT requests", ok, f"wall {wall} ms, slowest {max(o[2] for o in out)} ms, all IDs correct: {ok}")
    s = time.perf_counter()
    outs = await asyncio.gather(*[tts.synthesize_speech(spoken) for _ in range(4)])
    record("concurrency", "4 simultaneous TTS requests", all(outs), f"wall {int((time.perf_counter() - s) * 1000)} ms")

    passed = sum(r["ok"] for r in rows)
    say(f"\n{passed}/{len(rows)} checks passed" + (f"; FAILED: {', '.join(failures)}" if failures else ""))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
