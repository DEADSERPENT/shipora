"""How often does a spoken tracking number survive a phone line?

    cd backend-fastapi
    .venv/Scripts/python.exe scripts/stress_voice_ids.py [--n 15] [--json out.json]

For each channel condition, N fresh random tracking numbers are spoken by the TTS voice, degraded the way a phone call
degrades audio, transcribed by the real STT, and passed through the same correction + extraction + check-digit code the live
pipeline uses. Every attempt ends in exactly one outcome:

  exact       the right number was recovered
  safe        nothing usable / check digit failed -> the assistant asks the caller to repeat (an annoyance, not a harm)
  UNDETECTED  a number with a VALID check digit that is not the one spoken -> would look up (or miss) the wrong parcel.
              This is the only outcome that matters for safety; the check digit exists to keep it small.

Conditions: clean 22 kHz | phone (8 kHz band-limit + mu-law 8-bit quantisation) | phone + noise at 15 dB SNR | phone + noise at 8 dB SNR.
Limits: one synthetic English voice, so it measures channel damage, not speaker/accent variety."""

import argparse
import asyncio
import io
import json
import os
import re
import sys
import wave
from pathlib import Path

os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/shipora-stress"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from models.shipment import generate_tracking_number, tracking_checksum_ok  # noqa: E402
from services.stt import transcribe_audio  # noqa: E402
from services.tts import synthesize_speech  # noqa: E402
from voice.transcript_fix import fix_transcript, extract_id  # noqa: E402


def say(text=""):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _decode(wav_bytes: bytes, rate: int) -> np.ndarray:
    import av
    container = av.open(io.BytesIO(wav_bytes))
    resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
    chunks = []
    for frame in container.decode(audio=0):
        for out in resampler.resample(frame) or []:
            chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None) or []:
        chunks.append(out.to_ndarray().reshape(-1))
    container.close()
    return np.concatenate(chunks).astype(np.float32)


def _wav(samples: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def _mulaw(x: np.ndarray, mu: int = 255) -> np.ndarray:
    """G.711-style companding to 8 bits and back: the quantisation noise of a real phone codec."""
    y = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    q = np.round((y + 1) / 2 * 255) / 255 * 2 - 1
    return np.sign(q) * ((1 + mu) ** np.abs(q) - 1) / mu


def degrade(wav_bytes: bytes, condition: str, rng: np.random.Generator) -> bytes:
    if condition == "clean":
        return wav_bytes
    x = _decode(wav_bytes, 8000)                  # PyAV's resampler band-limits to 4 kHz: the telephone passband
    x = _mulaw(x)
    snr = {"phone": None, "phone+15dB": 15, "phone+8dB": 8}[condition]
    if snr is not None:
        power = float(np.mean(x ** 2)) or 1e-9
        x = x + rng.normal(0, np.sqrt(power / (10 ** (snr / 10))), x.shape).astype(np.float32)
    return _wav(x, 8000)


def outcome(true_id: str, transcript: str) -> str:
    got = extract_id(fix_transcript(transcript or ""))
    if got == true_id:
        return "exact"
    if got is None or not tracking_checksum_ok(got):
        return "safe"
    return "UNDETECTED"


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    rng = np.random.default_rng(7)
    conditions = ["clean", "phone", "phone+15dB", "phone+8dB"]
    ids = [generate_tracking_number() for _ in range(args.n)]
    say(f"{args.n} random tracking numbers x {len(conditions)} channel conditions (TTS -> degrade -> STT -> correction -> check digit)\n")

    audio = {}
    for tn in ids:
        spoken = "The tracking number is S H P " + " ".join(tn[3:]) + "."
        audio[tn] = await synthesize_speech(spoken)

    report, rows = {}, []
    for cond in conditions:
        tally = {"exact": 0, "safe": 0, "UNDETECTED": 0}
        for tn in ids:
            heard = await transcribe_audio(degrade(audio[tn], cond, rng), "call.wav")
            o = outcome(tn, heard)
            tally[o] += 1
            rows.append({"condition": cond, "id": tn, "heard": heard, "outcome": o})
        report[cond] = tally
        n = args.n
        say(f"{cond:<12} exact {tally['exact'] / n:>5.0%}   safe-reject {tally['safe'] / n:>5.0%}   UNDETECTED-wrong {tally['UNDETECTED'] / n:>5.0%}")
    bad = [r for r in rows if r["outcome"] == "UNDETECTED"]
    for r in bad[:5]:
        say(f"  undetected: said {r['id']} heard {r['heard']!r} ({r['condition']})")
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": report, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
