"""Local open-source voice providers (faster-whisper STT, Piper TTS) — alongside, not instead of, OpenAI.

Model inference is mocked everywhere: these tests never load a model, never need the optional packages
installed, and never touch the network. They check the provider wiring, the failure behaviour and the
WAV/MP3 content-type handling. Nothing here claims how the real models sound or perform."""
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from services import stt, tts

pytestmark = pytest.mark.anyio


def wav_bytes(n_frames=800) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


# ─── Registry / defaults ────────────────────────────────────────────────────
def test_openai_stays_the_default_and_both_providers_are_registered():
    # The code defaults, read from source: the live config.* values also reflect a developer's own .env
    # (which may already select the local providers), so they say nothing about the defaults.
    source = (Path(config.__file__)).read_text(encoding="utf-8")
    assert 'os.getenv("STT_PROVIDER", "openai")' in source and 'os.getenv("TTS_PROVIDER", "openai")' in source
    assert set(stt._PROVIDERS) == {"openai", "faster_whisper", "onnx_local"}
    assert set(tts._PROVIDERS) == {"openai", "piper"}
    assert stt._PROVIDERS["openai"] is stt.OpenAIWhisperProvider
    assert tts._PROVIDERS["openai"] is tts.OpenAITTSProvider


# ─── faster-whisper (STT) ───────────────────────────────────────────────────
class FakeWhisper:
    def __init__(self, texts):
        self.texts, self.calls = texts, []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio.read(), kwargs))
        return iter(SimpleNamespace(text=t) for t in self.texts), SimpleNamespace(language="en")


async def test_faster_whisper_joins_segments_and_passes_config(monkeypatch):
    fake = FakeWhisper([" where is", " my parcel? "])
    monkeypatch.setattr(stt, "_load_whisper_model", lambda: fake)
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    monkeypatch.setattr(config, "FASTER_WHISPER_LANGUAGE", "hi")
    assert await stt.transcribe_audio(b"RECORDING", "input.webm") == "where is my parcel?"
    audio, kwargs = fake.calls[0]
    assert audio == b"RECORDING" and kwargs["language"] == "hi"


async def test_faster_whisper_silence_returns_none(monkeypatch):
    monkeypatch.setattr(stt, "_load_whisper_model", lambda: FakeWhisper([]))
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    assert await stt.transcribe_audio(b"x", "input.webm") is None


async def test_faster_whisper_without_the_package_degrades_to_none_not_a_crash(monkeypatch):
    def boom():
        raise ImportError("No module named 'faster_whisper'")

    monkeypatch.setattr(stt, "_load_whisper_model", boom)
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    assert await stt.transcribe_audio(b"x", "input.webm") is None


async def test_faster_whisper_runtime_failure_degrades_to_none(monkeypatch):
    class Broken:
        def transcribe(self, *a, **k):
            raise RuntimeError("decode failed")

    monkeypatch.setattr(stt, "_load_whisper_model", lambda: Broken())
    monkeypatch.setattr(config, "STT_PROVIDER", "faster_whisper")
    assert await stt.transcribe_audio(b"x", "input.webm") is None


async def test_unknown_stt_provider_still_returns_none(monkeypatch):
    monkeypatch.setattr(config, "STT_PROVIDER", "nonsense")
    assert await stt.transcribe_audio(b"x", "input.webm") is None


# ─── ONNX Runtime Whisper (STT, for machines where CTranslate2 can't load) ──
class FakeOnnxModel:
    def __init__(self, text="where is my parcel"):
        self.text, self.calls = text, []

    def recognize(self, samples, **kwargs):
        self.calls.append((len(samples), kwargs))
        return self.text


def _use_fake_onnx(monkeypatch, model, samples=16000):
    import numpy as np

    monkeypatch.setattr(stt, "_load_onnx_model", lambda: model)
    monkeypatch.setattr(stt, "_decode_to_mono_16k", lambda audio: np.zeros(samples, dtype=np.float32))
    monkeypatch.setattr(config, "STT_PROVIDER", "onnx_local")


async def test_onnx_provider_transcribes_and_leaves_the_other_providers_alone(monkeypatch):
    model = FakeOnnxModel(" Where is my parcel? ")
    _use_fake_onnx(monkeypatch, model)
    monkeypatch.setattr(config, "ONNX_STT_LANGUAGE", None)
    assert await stt.transcribe_audio(b"x", "input.webm") == "Where is my parcel?"
    assert model.calls == [(16000, {"sample_rate": 16000})]                              # no language => Whisper auto-detects
    assert stt._PROVIDERS["faster_whisper"] is stt.FasterWhisperProvider and stt._PROVIDERS["openai"] is stt.OpenAIWhisperProvider


async def test_onnx_provider_passes_a_configured_language(monkeypatch):
    model = FakeOnnxModel()
    _use_fake_onnx(monkeypatch, model)
    monkeypatch.setattr(config, "ONNX_STT_LANGUAGE", "hi")
    await stt.transcribe_audio(b"x", "input.webm")
    assert model.calls[0][1] == {"sample_rate": 16000, "language": "hi"}


async def test_onnx_provider_truncates_overlong_recordings_instead_of_failing(monkeypatch):
    model = FakeOnnxModel()
    _use_fake_onnx(monkeypatch, model, samples=16000 * 90)                             # 90 s of audio
    monkeypatch.setattr(config, "ONNX_STT_MAX_SECONDS", 30)
    await stt.transcribe_audio(b"x", "input.webm")
    assert model.calls[0][0] == 16000 * 30


async def test_onnx_provider_empty_audio_or_transcript_returns_none(monkeypatch):
    _use_fake_onnx(monkeypatch, FakeOnnxModel(text="   "))
    assert await stt.transcribe_audio(b"x", "input.webm") is None                       # blank transcript
    _use_fake_onnx(monkeypatch, FakeOnnxModel(), samples=0)
    assert await stt.transcribe_audio(b"x", "input.webm") is None                       # nothing decoded


async def test_onnx_provider_import_failure_or_model_error_degrades_to_none(monkeypatch):
    def boom():
        raise ImportError("DLL load failed: blocked")

    monkeypatch.setattr(stt, "_load_onnx_model", boom)
    monkeypatch.setattr(config, "STT_PROVIDER", "onnx_local")
    assert await stt.transcribe_audio(b"x", "input.webm") is None

    class Broken(FakeOnnxModel):
        def recognize(self, *a, **k):
            raise RuntimeError("inference failed")

    _use_fake_onnx(monkeypatch, Broken())
    assert await stt.transcribe_audio(b"x", "input.webm") is None


def test_onnx_loader_downloads_only_the_wanted_precision_once_and_never_into_the_repo_tree(tmp_path, monkeypatch):
    import sys

    downloads, loads = [], []

    def snapshot_download(repo, local_dir, allow_patterns):
        downloads.append((repo, local_dir, allow_patterns))
        (tmp_path / "onnx_stt" / "whisper-base").mkdir(parents=True, exist_ok=True)
        (tmp_path / "onnx_stt" / "whisper-base" / "whisper-base_beamsearch.int8.onnx").write_bytes(b"x")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    monkeypatch.setitem(sys.modules, "onnx_asr", SimpleNamespace(load_model=lambda name, **kw: loads.append((name, kw)) or "MODEL"))
    monkeypatch.setattr(stt, "_onnx_model", None)
    monkeypatch.setattr(config, "LOCAL_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ONNX_STT_MODEL", "whisper-base")
    monkeypatch.setattr(config, "ONNX_STT_QUANTIZATION", "int8")
    monkeypatch.setattr(config, "ONNX_STT_DEVICE", "cpu")
    try:
        assert stt._load_onnx_model() == "MODEL"
        assert downloads == [("istupakov/whisper-base-onnx", str(tmp_path / "onnx_stt" / "whisper-base"), ["*.json", "*.txt", "*int8.onnx"])]
        name, kw = loads[0]
        assert name == "whisper-base" and kw["quantization"] == "int8" and kw["providers"] == ["CPUExecutionProvider"]
        assert kw["path"] == str(tmp_path / "onnx_stt" / "whisper-base")
        stt._onnx_model = None                                                           # files now exist: no second download
        stt._load_onnx_model()
        assert len(downloads) == 1
    finally:
        stt._onnx_model = None


def test_onnx_decoder_resamples_to_16k_mono_float32():
    pytest.importorskip("av")
    import numpy as np

    samples = stt._decode_to_mono_16k(wav_bytes(n_frames=22050))                         # 1 s @ 22.05 kHz mono
    assert samples.dtype == np.float32 and samples.ndim == 1
    assert abs(len(samples) - 16000) < 400


# ─── Piper (TTS) ────────────────────────────────────────────────────────────
class FakePiperNew:
    """piper-tts >= 1.3 API."""
    def synthesize_wav(self, text, wav_file):
        self.text = text
        wav_file.setnchannels(1); wav_file.setsampwidth(2); wav_file.setframerate(22050)
        wav_file.writeframes(b"\x01\x00" * 500)


class FakePiperLegacy:
    """piper-tts 1.2 API."""
    def synthesize(self, text, wav_file):
        self.text = text
        wav_file.setnchannels(1); wav_file.setsampwidth(2); wav_file.setframerate(22050)
        wav_file.writeframes(b"\x01\x00" * 500)


@pytest.mark.parametrize("voice_cls", [FakePiperNew, FakePiperLegacy])
async def test_piper_returns_a_playable_wav_for_either_piper_api(monkeypatch, voice_cls):
    voice = voice_cls()
    monkeypatch.setattr(tts, "_load_piper_voice", lambda: voice)
    monkeypatch.setattr(config, "TTS_PROVIDER", "piper")
    data = await tts.synthesize_speech("Your parcel is out for delivery.")
    assert data[:4] == b"RIFF" and tts.audio_mime_type(data) == "audio/wav"
    with wave.open(io.BytesIO(data)) as w:                     # genuinely parseable WAV, not just a header
        assert w.getnframes() == 500 and w.getframerate() == 22050
    assert voice.text == "Your parcel is out for delivery."


async def test_piper_text_is_trimmed_like_every_other_provider(monkeypatch):
    voice = FakePiperNew()
    monkeypatch.setattr(tts, "_load_piper_voice", lambda: voice)
    monkeypatch.setattr(config, "TTS_PROVIDER", "piper")
    await tts.synthesize_speech("a" * 5000)
    assert len(voice.text) == min(tts._MAX_CHARS, config.VOICE_MAX_SPOKEN_CHARS)   # spoken replies are shorter than the chat text


async def test_piper_missing_voice_file_or_package_returns_none(monkeypatch):
    monkeypatch.setattr(config, "TTS_PROVIDER", "piper")
    monkeypatch.setattr(tts, "_load_piper_voice", lambda: None)                       # voice file not downloaded
    assert await tts.synthesize_speech("hello") is None

    def boom():
        raise ImportError("No module named 'piper'")

    monkeypatch.setattr(tts, "_load_piper_voice", boom)                               # package not installed
    assert await tts.synthesize_speech("hello") is None


async def test_piper_empty_synthesis_is_treated_as_no_audio(monkeypatch):
    class Silent:
        def synthesize_wav(self, text, wav_file):
            wav_file.setnchannels(1); wav_file.setsampwidth(2); wav_file.setframerate(22050)    # header only

    monkeypatch.setattr(tts, "_load_piper_voice", lambda: Silent())
    monkeypatch.setattr(config, "TTS_PROVIDER", "piper")
    assert await tts.synthesize_speech("hello") is None


def test_piper_voice_loader_reports_a_missing_file_without_importing_a_model(tmp_path, monkeypatch):
    """Real loader, fake `piper` module: a missing .onnx must yield None (and never reach PiperVoice.load)."""
    import sys

    loaded = []
    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=SimpleNamespace(load=lambda p: loaded.append(p))))
    monkeypatch.setattr(tts, "_piper_voice", None)
    monkeypatch.setattr(config, "LOCAL_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "missing.onnx")
    assert tts._load_piper_voice() is None and loaded == []

    (tmp_path / "piper").mkdir()
    (tmp_path / "piper" / "present.onnx").write_bytes(b"not a real model")
    monkeypatch.setattr(config, "PIPER_VOICE", "present.onnx")
    assert tts._load_piper_voice() is not None or loaded                                  # reaches PiperVoice.load with the resolved path
    assert loaded and loaded[0].endswith("present.onnx")
    monkeypatch.setattr(tts, "_piper_voice", None)


# ─── Content type ───────────────────────────────────────────────────────────
def test_audio_mime_type_distinguishes_wav_from_mp3():
    assert tts.audio_mime_type(wav_bytes()) == "audio/wav"
    assert tts.audio_mime_type(b"ID3\x04\x00\x00" + b"\x00" * 20) == "audio/mpeg"
    assert tts.audio_mime_type(b"\xff\xfb\x90\x00" + b"\x00" * 20) == "audio/mpeg"
    assert tts.audio_mime_type(b"") == "audio/mpeg"                                       # never raises


async def test_voice_route_reports_the_real_audio_type(client, monkeypatch):
    import base64

    from routes import voice as voice_route

    async def fake_turn(audio, filename, session_id, user, speak=True):
        return {"reply": "ok", "source": "builtin", "agent": "general", "sentiment": "neutral",
                "transcript": "hi", "audioBytes": audio_bytes, "latencyMs": {}}

    monkeypatch.setattr(voice_route, "run_voice_turn", fake_turn)
    files = {"audio": ("input.webm", b"x" * 100, "audio/webm")}

    audio_bytes = wav_bytes()
    body = (await client.post("/api/voice/chat", files=files)).json()
    assert body["audioMimeType"] == "audio/wav" and base64.b64decode(body["audioBase64"]) == audio_bytes

    audio_bytes = b"ID3\x04\x00\x00" + b"\x00" * 20                                       # OpenAI-style MP3 is unchanged
    assert (await client.post("/api/voice/chat", files=files)).json()["audioMimeType"] == "audio/mpeg"

    audio_bytes = None                                                                    # speak=false / provider unavailable
    body = (await client.post("/api/voice/chat", files=files)).json()
    assert body["audioBase64"] is None and body["audioMimeType"] is None


# ─── Speech-clean text (what the TTS provider is actually given) ────────────
def test_speech_text_strips_markdown_but_keeps_the_words():
    reply = "**Tracking a parcel:**\n• Every shipment gets a number starting with **SHP**.\n• Enter it on the [tracking page](http://x/track) to see its `status`.\n\n## Next\n1. Wait\n- done"
    assert tts.speech_text(reply) == "Tracking a parcel: Every shipment gets a number starting with SHP. Enter it on the tracking page to see its status. Next. Wait. done."
    assert tts.speech_text("**Status:** Out for delivery\n- Estimated delivery: Today") == "Status: Out for delivery. Estimated delivery: Today."


def test_speech_text_leaves_identifiers_and_arithmetic_alone():
    assert tts.speech_text("Your parcel_id is snake_case, 5*3 stays, *italic* and _also_ go.") == "Your parcel_id is snake_case, 5*3 stays, italic and also go."
    assert tts.speech_text("order_ref") == "order_ref."    # a closing period is added to every line: it is the spoken pause
    assert tts.speech_text("") == "" and tts.speech_text("**  **") == ""


@pytest.mark.parametrize("provider", ["piper", "openai"])
async def test_every_provider_is_given_speech_clean_text_and_nothing_when_there_is_nothing_to_say(monkeypatch, provider):
    heard = []

    class Spy(tts.TTSProvider):
        def speak(self, text):
            heard.append(text)
            return b"RIFF....WAVE" + b"\x00" * 60

    monkeypatch.setitem(tts._PROVIDERS, provider, Spy)
    monkeypatch.setattr(config, "TTS_PROVIDER", provider)
    await tts.synthesize_speech("**Out for delivery**\n- arriving today")
    assert heard == ["Out for delivery. arriving today."]
    assert await tts.synthesize_speech("**  **") is None and len(heard) == 1            # nothing speakable: provider not called
