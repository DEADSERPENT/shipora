# Local voice (faster-whisper / ONNX Whisper + Piper)

ShipBot's voice pipeline is STT → agents → TTS (see `VOICE_ARCHITECTURE.md`). Each speech stage has a cloud default and local, open-source alternatives, chosen by environment variable:

| Stage | `openai` (default) | local, no API key |
|---|---|---|
| STT | OpenAI Whisper API (`whisper-1`) | `STT_PROVIDER=faster_whisper` or `onnx_local` |
| TTS | OpenAI TTS (`tts-1`) → **MP3** | `TTS_PROVIDER=piper` → **WAV** |

The reasoning layer is unchanged: Gemini still does classification and tool-calling. The OpenAI providers are
untouched; the two stages can be mixed (e.g. local STT with OpenAI TTS).

## Which local STT?

| | `faster_whisper` | `onnx_local` |
|---|---|---|
| Engine | CTranslate2 (native library) | ONNX Runtime via the pure-Python `onnx-asr` package |
| Use when | Linux / GPU servers | **Windows machines whose application-control policy blocks CTranslate2** (`DLL load failed … An Application Control policy has blocked this file`), or anywhere you want a small CPU-only setup |
| Model | `FASTER_WHISPER_MODEL` (tiny … large-v3) | `ONNX_STT_MODEL=whisper-base` (multilingual Whisper base, int8 ≈ 105 MB on disk) |

Don't weaken an OS security policy to make `faster_whisper` load — use `onnx_local` instead.

## Status — read this first

* The provider code, configuration, error handling and WAV/MP3 content-type handling are covered by unit tests
  (`tests/test_local_voice_providers.py`) **with the models mocked**.
* **Verified end to end on one Windows machine (CPU, no GPU):** real audio (a WAV and a browser-style webm/opus
  recording) → `onnx_local` Whisper-base → ShipBot → Piper → valid `audio/wav`, through the real `/api/voice/chat`.
  Measured: STT ≈ 0.9–1.1 s for a 4 s question (warm; ≈ 3 s on the first call, which loads the model), Piper ≈ 1–1.7 s
  for a ≈ 17 s reply (≈ 4.8 s on the first call). One short English test sentence only — this is not an accuracy benchmark.
  `faster_whisper` could not be tried on that machine (blocked by policy), so it remains verified only with mocks.
* **English is the supported TTS language.** faster-whisper transcribes many languages (Hindi, Kannada, … —
  leave `FASTER_WHISPER_LANGUAGE` empty to auto-detect). Piper needs a voice per language; Indic voices are
  limited, and none has been tested here. Don't assume non-English spoken replies work until you've listened to one.
  If a Piper voice isn't usable for a language, the text reply still appears — only playback is skipped.

## Install

The packages are optional and kept out of `requirements.txt` (and out of the Docker image):

```bash
cd backend-fastapi
.venv/Scripts/python -m pip install -r requirements-local-voice.txt     # Linux/macOS: .venv/bin/python
```

## Models (never committed)

Everything lives in `backend-fastapi/local_models/` (git-ignored and docker-ignored; override with
`LOCAL_MODELS_DIR`). It is not `models/` because that is the Beanie documents package.

**faster-whisper** — set a size name and the model downloads into `local_models/whisper/` the first time a
recording is transcribed (`tiny` ≈ 75 MB, `small` ≈ 500 MB, `medium` ≈ 1.5 GB, `large-v3` ≈ 3 GB). To fetch it
ahead of time instead, put a converted model directory at `local_models/whisper/<name>/` or point
`FASTER_WHISPER_MODEL` at an absolute directory.

**onnx_local** — `whisper-base` downloads automatically on first use into `local_models/onnx_stt/whisper-base/` (only
the precision in `ONNX_STT_QUANTIZATION`, default `int8`, plus tokenizer files — not the whole repository). Set
`ONNX_STT_QUANTIZATION=` (empty) for full precision (≈ 400 MB). Other `onnx-asr` model names work only if you place
their files in `local_models/onnx_stt/<model-name>/` yourself — untested here. Recordings longer than
`ONNX_STT_MAX_SECONDS` (30) are truncated; Whisper processes 30-second windows. `ONNX_STT_DEVICE=cuda` needs
`onnxruntime-gpu` in place of `onnxruntime` and has not been tried (use faster-whisper for GPU speech recognition instead, below).

**Piper** — download a voice (an `.onnx` file *and* its `.onnx.json` next to it) into `local_models/piper/`:

```bash
.venv/Scripts/python -m piper.download_voices en_US-lessac-medium --download-dir local_models/piper
```

(`piper.download_voices` ships with piper-tts ≥ 1.3. Otherwise download both files for the voice from
<https://huggingface.co/rhasspy/piper-voices> by hand.) A voice is ≈ 60 MB.

## Configure (`backend-fastapi/.env`)

```env
STT_PROVIDER=faster_whisper
TTS_PROVIDER=piper

FASTER_WHISPER_MODEL=small            # tiny | base | small | medium | large-v3, or a directory
FASTER_WHISPER_DEVICE=auto            # auto | cpu | cuda
FASTER_WHISPER_COMPUTE_TYPE=default   # float16 on a GPU, int8 on CPU
FASTER_WHISPER_LANGUAGE=              # empty = auto-detect per recording
PIPER_VOICE=en_US-lessac-medium.onnx  # file name in local_models/piper/, or an absolute path

# or, STT_PROVIDER=onnx_local:
ONNX_STT_MODEL=whisper-base
ONNX_STT_QUANTIZATION=int8            # empty = full precision
ONNX_STT_DEVICE=cpu                   # cpu | cuda
ONNX_STT_LANGUAGE=                    # e.g. en, hi, kn; empty = auto-detect
```

Switch back to the cloud providers with `STT_PROVIDER=openai` / `TTS_PROVIDER=openai` (needs `OPENAI_API_KEY`).

## Behaviour when something is missing

Voice never crashes the app. If the package isn't installed or the model/voice file is missing, the provider logs a
single clear error (`stt_provider_unavailable` / `tts_provider_unavailable`, with a hint) and the pipeline carries on:
STT → the route reports voice as unavailable; TTS → the reply is returned as text with no audio.

## Audio format

Piper returns WAV, so `/api/voice/chat` reports `audioMimeType` from the audio itself (`audio/wav` or `audio/mpeg`)
and the browser plays whichever it gets. No ffmpeg conversion is involved. faster-whisper decodes browser
recordings (webm/opus, mp4) with its bundled PyAV, so ffmpeg is not required for STT either.

## Text sent to the voice

Replies are written for the chat bubble (markdown, bullets). Before any TTS provider — OpenAI or Piper — sees them,
`services/tts.py: speech_text()` strips the markdown syntax and turns line breaks into sentence pauses, so the voice
reads "Tracking a parcel: every shipment…" instead of "star star Tracking a parcel star star". The on-screen text is unchanged.


## GPU speech recognition (faster-whisper on NVIDIA CUDA)

`STT_PROVIDER=faster_whisper` with the default `FASTER_WHISPER_DEVICE=auto` runs on the GPU when CUDA works. On Windows and
Linux `pip install -r requirements-local-voice.txt` also installs `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`; `services/stt.py`
registers their DLL folders itself. If the CUDA libraries are missing or the model will not load on the GPU it logs
`stt_gpu_fallback` and continues on CPU (`int8`), so voice never stops working because of a driver problem.

Measured on an RTX 3060 Laptop GPU (6 GB), Whisper `small`, 4-second clip: **~290 ms on GPU vs ~3,200 ms on CPU** (same transcript).
Ollama (`LLM_PROVIDER=ollama`) uses the GPU by itself; check with `ollama ps` (PROCESSOR should read `100% GPU`). A model that does
not fit in free VRAM (e.g. `qwen3:8b` on 6 GB while other things hold memory) is split across CPU and GPU and becomes several
times slower — `qwen2.5:3b` stays fully resident. Piper and the ONNX STT provider run on CPU.

## Verification scripts

| Script | What it checks |
|---|---|
| `scripts/verify_sandwich.py` | One caller turn through the REAL STT, agents (against an in-memory database) and TTS, then `/api/voice/chat`. |
| `scripts/audit_voice.py` | Real STT/TTS robustness: speaking speed, white noise, how the ID is spoken, empty/silent/garbage/truncated/long audio, latency, memory, concurrency. |

Not covered by either (no recordings available): Indian-English and other accents, Hindi, Kannada. Piper only ships the `en_US` voice
here; anything else needs real human recordings.
