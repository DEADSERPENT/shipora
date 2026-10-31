"""Dictation and playback endpoints, and the rule that spoken input gets no extra power: audio is never stored, the text goes
back to the person to review, and a hands-free spoken "yes" cannot file a complaint on its own."""
import pytest

import config
from agents import complaints_agent, orchestrator
from models.chat_analytics import ChatAnalytics
from models.complaint_draft import ComplaintDraft
from models.delivery_issue import DeliveryIssue
from routes import voice as voice_routes
from tests.conftest import register
from tests.test_complaint_confirmation import ARGS, customer, model, say  # noqa: F401  (fixtures + helpers)

pytestmark = pytest.mark.anyio


def audio(data=b"RIFFxxxxWAVEfmt ", name="clip.webm"):
    return {"audio": (name, data, "audio/webm")}


# ── POST /api/voice/transcribe ──────────────────────────────────────────────
async def test_transcribe_returns_the_text_for_review_and_stores_nothing(client, monkeypatch):
    async def stt(raw, name):
        return "where is shipment S H P 4 8 2 1 7 3 9 0"
    monkeypatch.setattr(voice_routes, "transcribe_audio", stt)
    r = await client.post("/api/voice/transcribe", files=audio())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"text"} and "SHP48217390" in body["text"].replace(" ", "")      # spoken IDs are repaired for the box
    assert await ChatAnalytics.find_all().count() == 0                                     # nothing logged, nothing kept
    assert await DeliveryIssue.find_all().count() == 0                                     # and dictation never acts


async def test_transcribe_runs_no_assistant_and_sends_nothing(client, monkeypatch):
    async def stt(raw, name):
        return "yes"
    called = []

    async def boom(*a, **k):
        called.append(1)
    monkeypatch.setattr(voice_routes, "transcribe_audio", stt)
    monkeypatch.setattr(orchestrator, "route_and_reply", boom)
    r = await client.post("/api/voice/transcribe", files=audio())
    assert r.status_code == 200 and not called


async def test_transcribe_failures_are_explained(client, monkeypatch):
    async def none(raw, name):
        return None
    monkeypatch.setattr(voice_routes, "transcribe_audio", none)
    r = await client.post("/api/voice/transcribe", files=audio())
    assert r.status_code == 422 and "type" in r.json()["message"].lower()


async def test_transcribe_rejects_oversized_and_empty_recordings(client, monkeypatch):
    monkeypatch.setattr(config, "VOICE_MAX_UPLOAD_BYTES", 100)
    big = await client.post("/api/voice/transcribe", files=audio(b"x" * 500))
    assert big.status_code == 413
    empty = await client.post("/api/voice/transcribe", files=audio(b""))
    assert empty.status_code in (413, 422)


async def test_transcribe_and_speak_are_rate_limited_like_the_other_voice_calls(client, monkeypatch):
    import ratelimit

    async def stt(raw, name):
        return "hello"

    async def tts(text):
        return b"RIFF"
    monkeypatch.setattr(voice_routes, "transcribe_audio", stt)
    monkeypatch.setattr(voice_routes, "synthesize_speech", tts)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_VOICE", "2/60")
    monkeypatch.setenv("RATE_LIMIT_SPEAK", "2/60")
    ratelimit.limiter.reset()
    assert [(await client.post("/api/voice/transcribe", files=audio())).status_code for _ in range(3)] == [200, 200, 429]
    assert [(await client.post("/api/voice/speak", json={"text": "hi"})).status_code for _ in range(3)] == [200, 200, 429]
    ratelimit.limiter.reset()


# ── POST /api/voice/speak ───────────────────────────────────────────────────
async def test_speak_returns_audio_and_stores_nothing(client, monkeypatch):
    async def tts(text):
        return b"RIFF....WAVEdata"
    monkeypatch.setattr(voice_routes, "synthesize_speech", tts)
    r = await client.post("/api/voice/speak", json={"text": "Your parcel is on its way."})
    assert r.status_code == 200 and r.content.startswith(b"RIFF") and r.headers["content-type"].startswith("audio/")
    assert await ChatAnalytics.find_all().count() == 0


async def test_speak_validates_its_input(client, monkeypatch):
    async def tts(text):
        return b"RIFF"
    monkeypatch.setattr(voice_routes, "synthesize_speech", tts)
    assert (await client.post("/api/voice/speak", json={"text": ""})).status_code == 422
    assert (await client.post("/api/voice/speak", json={"text": "x" * 5000})).status_code == 422


async def test_speak_reports_an_unavailable_voice_instead_of_failing_silently(client, monkeypatch):
    async def none(text):
        return None
    monkeypatch.setattr(voice_routes, "synthesize_speech", none)
    r = await client.post("/api/voice/speak", json={"text": "hello"})
    assert r.status_code == 503 and r.json()["message"]


# ── spoken input gets no extra power ────────────────────────────────────────
async def test_a_hands_free_spoken_yes_never_files_a_complaint(client, model):
    u, _ = await customer(client, "v1@t.test")
    model.update(tool="draft_complaint", args=ARGS, text="x")
    await complaints_agent.handle("my parcel arrived damaged", [], "neutral", u, session_id="v-s1")
    reply = await complaints_agent.handle("yes", [], "neutral", u, session_id="v-s1", channel="voice_auto")
    assert await DeliveryIssue.find_all().count() == 0
    assert "tap" in reply.lower() and (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).status == "pending"
    typed = await complaints_agent.handle("yes", [], "neutral", u, session_id="v-s1")          # typed or tapped: the same draft files
    assert await DeliveryIssue.find_all().count() == 1 and "filed" in typed.lower()


async def test_a_spoken_no_still_cancels(client, model):
    u, _ = await customer(client, "v2@t.test")
    model.update(tool="draft_complaint", args=ARGS, text="x")
    await complaints_agent.handle("my parcel arrived damaged", [], "neutral", u, session_id="v-s2")
    await complaints_agent.handle("no", [], "neutral", u, session_id="v-s2", channel="voice_auto")
    assert (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).status == "declined"


async def test_the_voice_channel_reaches_the_same_authorization_rules(client, monkeypatch):
    async def classify(message, history):
        return {"agent": "tracking", "sentiment": "neutral"}

    async def none(*a, **k):
        return None
    monkeypatch.setattr(orchestrator, "classify", classify)
    for mod in (orchestrator.tracking_agent, orchestrator.general_agent):
        monkeypatch.setattr(mod, "run_tool_agent", none)
    out = await orchestrator.route_and_reply("Which vehicles are live right now?", [], {"id": "1" * 24, "role": "driver"}, channel="voice_auto")
    assert "KA" not in out["reply"] and "operations only" in out["reply"].lower()


async def test_stored_transcripts_hold_the_persons_words_not_the_language_instruction(client):
    wrapped = "Reply naturally in English.\nDo not use markdown.\n\nUser's message: How do I create a shipment?"
    r = await client.post("/api/chat", json={"message": wrapped, "sessionId": "wrap-1"})
    assert r.status_code == 200
    row = await ChatAnalytics.find_one(ChatAnalytics.sessionId == "wrap-1")
    assert row.transcript == "How do I create a shipment?"
