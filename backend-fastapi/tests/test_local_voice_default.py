"""The local-voice default: faster-whisper small.en + Kokoro, no API key, no hosted fallback, bounded concurrency.

Model inference is faked except in test_real_models_round_trip (opt-in: RUN_REAL_VOICE=1, needs the models from
docs/LOCAL_VOICE.md and a GPU or patience)."""
import asyncio
import io
import os
import subprocess
import sys
import threading
import time
import types
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from services import speech_limits, stt, tts
from services.speech_limits import SpeechModelError, SpeechTimeout

pytestmark = pytest.mark.anyio
BACKEND = Path(config.__file__).resolve().parent


def wav_bytes(seconds=0.2, rate=24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return buf.getvalue()


# ─── Startup / defaults without any credentials ─────────────────────────────
def test_defaults_are_local_with_pinned_models_in_a_clean_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI", "STT_", "TTS_", "FASTER_WHISPER", "KOKORO"))}
    env.update(JWT_SECRET="Vq3-ZTest-Only-Secret-0f9aKd7LmXc2RhE8yBw5NpJs", APP_ENV="test")
    code = ("import dotenv; dotenv.load_dotenv=lambda *a, **k: None; import config as c; c.validate();"   # ignore a developer's own .env
            
            "print(c.STT_PROVIDER, c.TTS_PROVIDER, c.FASTER_WHISPER_MODEL, c.FASTER_WHISPER_LANGUAGE, c.FASTER_WHISPER_BEAM_SIZE, c.KOKORO_VOICE, c.OPENAI_API_KEY)")
    out = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(BACKEND)!r}); {code}"], cwd=str(BACKEND), env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["faster_whisper", "kokoro", "Systran/faster-whisper-small.en", "en", "3", "af_heart", "None"]


def test_check_environment_never_asks_for_an_openai_key():
    env = {"JWT_SECRET": "Vq3-ZTest-Only-Secret-0f9aKd7LmXc2RhE8yBw5NpJs", "APP_ENV": "test"}
    assert config.check_environment(env) == []


async def test_health_works_without_openai_credentials(client, monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    assert (await client.get("/api/health")).status_code == 200


def test_model_revisions_are_pinned_commits():
    for rev in (config.FASTER_WHISPER_REVISION, config.KOKORO_REVISION):
        assert rev and len(rev) == 40 and int(rev, 16) >= 0


# ─── Provider selection ──────────────────────────────────────────────────────
def test_local_registries_and_audio_formats():
    assert stt._PROVIDERS["faster_whisper"] is stt.FasterWhisperProvider and tts._PROVIDERS["kokoro"] is tts.KokoroTTSProvider
    assert tts.audio_mime_type(wav_bytes()) == "audio/wav"


async def test_faster_whisper_gets_the_english_settings(monkeypatch):
    seen = {}

    class Fake:
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return iter([SimpleNamespace(text=" hello ")]), None

    monkeypatch.setattr(stt, "_load_whisper_model", lambda: Fake())
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    assert await stt.transcribe_audio(b"x", "a.webm") == "hello"
    assert seen == {"language": "en", "beam_size": 3, "vad_filter": True}


def test_model_load_is_given_the_pinned_revision_and_tries_gpu_then_cpu(monkeypatch):
    calls = []

    class FakeModel:
        def __init__(self, source, device, compute_type, download_root, revision=None):
            calls.append((source, device, compute_type, revision))
            if device != "cpu":
                raise RuntimeError("no cuda")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setattr(stt, "_whisper_model", None)
    monkeypatch.setattr(config, "FASTER_WHISPER_DEVICE", "cuda")
    stt._load_whisper_model()
    assert [c[1:3] for c in calls] == [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    assert all(c[0] == "Systran/faster-whisper-small.en" and c[3] == config.FASTER_WHISPER_REVISION for c in calls)
    monkeypatch.setattr(stt, "_whisper_model", None)


# ─── Kokoro ──────────────────────────────────────────────────────────────────
class FakePipeline:
    def __init__(self, fail_first_with=None):
        self.calls, self.fail = [], fail_first_with
        self.model = SimpleNamespace(to=lambda d: None)

    def __call__(self, text, voice, speed):
        import torch
        self.calls.append((text, voice, speed))
        if self.fail:
            err, self.fail = self.fail, None
            raise err
        yield SimpleNamespace(audio=torch.full((2400,), 0.25))
        yield SimpleNamespace(audio=torch.full((2400,), -0.25))


def _install_kokoro(monkeypatch, pipeline, device="cpu"):
    monkeypatch.setattr(tts, "_kokoro_state", (pipeline, device, "voices/af_heart.pt"))
    monkeypatch.setattr(config, "TTS_PROVIDER", "kokoro")


async def test_kokoro_returns_24khz_pcm16_wav(monkeypatch):
    pytest.importorskip("torch")
    pipe = FakePipeline()
    _install_kokoro(monkeypatch, pipe)
    audio = await tts.synthesize_speech("Your parcel is out for delivery.")
    assert tts.audio_mime_type(audio) == "audio/wav"
    w = wave.open(io.BytesIO(audio))
    assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (24000, 1, 2, 4800)
    assert pipe.calls[0][0] == "Your parcel is out for delivery." and pipe.calls[0][2] == config.KOKORO_SPEED


async def test_kokoro_gpu_out_of_memory_continues_on_cpu(monkeypatch):
    torch = pytest.importorskip("torch")
    pipe = FakePipeline(fail_first_with=RuntimeError("CUDA out of memory"))
    moved = []
    pipe.model = SimpleNamespace(to=moved.append)
    _install_kokoro(monkeypatch, pipe, device="cuda")
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    assert await tts.synthesize_speech("Hello there.")
    assert moved == ["cpu"] and tts._kokoro_state[1] == "cpu" and len(pipe.calls) == 2


async def test_kokoro_not_installed_is_reported_and_never_falls_back_to_openai(monkeypatch, caplog):
    monkeypatch.setattr(tts, "_kokoro_state", None)
    monkeypatch.setattr(config, "TTS_PROVIDER", "kokoro")
    monkeypatch.setitem(sys.modules, "kokoro", None)   # import raises ImportError
    called = []
    monkeypatch.setattr(tts.OpenAITTSProvider, "speak", lambda self, t: called.append(t))
    with caplog.at_level("ERROR"):
        assert await tts.synthesize_speech("Hello.") is None
    assert not called
    assert any("requirements-local-voice.txt" in getattr(r, "error", "") for r in caplog.records)


async def test_missing_whisper_model_is_reported_and_never_falls_back_to_openai(monkeypatch, caplog):
    def broken():
        raise SpeechModelError("Could not load speech-to-text model 'x'. Check network access to huggingface.co")
    monkeypatch.setattr(stt, "_load_whisper_model", broken)
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-should-never-be-used")
    called = []
    monkeypatch.setattr(stt.OpenAIWhisperProvider, "transcribe", lambda self, a, f: called.append(1))
    with caplog.at_level("ERROR"):
        assert await stt.transcribe_audio(b"x", "a.webm") is None
    assert not called and any("huggingface.co" in getattr(r, "error", "") for r in caplog.records)


async def test_unknown_provider_does_not_pick_another(monkeypatch):
    monkeypatch.setattr(config, "TTS_PROVIDER", "nonsense")
    monkeypatch.setattr(config, "STT_PROVIDER", "nonsense")
    assert await tts.synthesize_speech("hi") is None and await stt.transcribe_audio(b"x", "a") is None


async def test_voice_endpoint_with_failed_local_models_answers_422_not_a_hosted_call(client, monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-should-never-be-used")
    monkeypatch.setattr(stt, "_load_whisper_model", lambda: (_ for _ in ()).throw(SpeechModelError("model missing")))
    r = await client.post("/api/voice/chat", files={"audio": ("a.wav", b"x" * 100, "audio/wav")})
    assert r.status_code == 422


# ─── Concurrency + timeouts ──────────────────────────────────────────────────
async def test_concurrency_is_capped(monkeypatch):
    monkeypatch.setattr(config, "VOICE_TTS_CONCURRENCY", 2)
    running, peak, lock = 0, 0, threading.Lock()

    def work():
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return 1

    assert await asyncio.gather(*[speech_limits.run_limited("tts", work) for _ in range(8)]) == [1] * 8
    assert peak == 2


async def test_queue_wait_times_out_and_the_slot_is_held_until_the_thread_ends(monkeypatch):
    monkeypatch.setattr(config, "VOICE_STT_CONCURRENCY", 1)
    monkeypatch.setattr(config, "VOICE_STT_TIMEOUT_SECONDS", 0.15)
    started = []
    gate = threading.Event()

    def slow():
        started.append(1)
        gate.wait(2)

    first = asyncio.ensure_future(speech_limits.run_limited("stt", slow))
    with pytest.raises(SpeechTimeout):
        await first                                   # running too long
    with pytest.raises(SpeechTimeout):                # the timed-out thread still owns the only slot
        await speech_limits.run_limited("stt", lambda: started.append(2))
    assert started == [1]
    gate.set()
    await asyncio.sleep(0.1)
    assert await speech_limits.run_limited("stt", lambda: "ok") == "ok"


async def test_stt_timeout_returns_none_not_a_provider_switch(monkeypatch):
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    monkeypatch.setattr(config, "VOICE_STT_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(stt, "_load_whisper_model", lambda: SimpleNamespace(transcribe=lambda *a, **k: time.sleep(0.4)))
    assert await stt.transcribe_audio(b"x", "a.webm") is None


# ─── Opt-in: real models, real audio ─────────────────────────────────────────
@pytest.mark.skipif(os.environ.get("RUN_REAL_VOICE") != "1", reason="set RUN_REAL_VOICE=1 (needs the local models, see docs/LOCAL_VOICE.md)")
async def test_real_models_round_trip(monkeypatch):
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    monkeypatch.setattr(config, "TTS_PROVIDER", "kokoro")
    monkeypatch.setattr(config, "VOICE_STT_TIMEOUT_SECONDS", 300)
    monkeypatch.setattr(config, "VOICE_TTS_TIMEOUT_SECONDS", 300)
    audio = await tts.synthesize_speech("Where is my parcel? Please check the status.")
    assert audio and tts.audio_mime_type(audio) == "audio/wav"
    heard = (await stt.transcribe_audio(audio, "reply.wav") or "").lower()
    assert "parcel" in heard and "status" in heard
