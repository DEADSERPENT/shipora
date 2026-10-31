"""The voice sandwich (STT -> agents -> TTS): stage order, grounding, resilience when the LLM is down, and the
speech-specific problem of spelled tracking numbers. STT/TTS are stubbed here (the real-model run is
scripts/verify_sandwich.py); everything between them is real."""
import pytest

from models.customer import Customer, Location
from models.shipment import ParcelDetails, Party, Shipment
from services import ollama_client
from tests.conftest import register
from tools.shipment_tools import execute_get_shipment_status, extract_tracking_number
from voice import pipeline

pytestmark = pytest.mark.anyio


async def _shipment(customer_id, tracking, status="OUT_FOR_DELIVERY"):
    s = Shipment(trackingNumber=tracking, customerId=customer_id, customerName="C",
                 sender=Party(name="S", phone="9880000099", address="Sender Rd", location=Location(lat=12.93, lng=77.62)),
                 recipient=Party(name="R", phone="9770000077", address="Drop Rd", location=Location(lat=12.97, lng=77.64)),
                 parcel=ParcelDetails(), status=status)
    s.record(status, "admin")
    await s.insert()
    return s


@pytest.mark.parametrize("spoken", ["SHP1A2B3C4D5E", "S H P 1 A 2 B 3 C 4 D 5 E", "shp-1a-2b-3c-4d-5e", "S.H.P. 1 A 2 B 3 C 4 D 5 E", "it is shp1a2b3c4d5e please"])
def test_spoken_tracking_number_variants_are_normalised(spoken):
    assert extract_tracking_number(f"where is {spoken}") == "SHP1A2B3C4D5E"


def test_no_id_no_extraction():
    assert extract_tracking_number("where is my parcel") is None and extract_tracking_number("SHP12") is None


async def test_voice_round_trip_stage_order_and_grounding(client, monkeypatch):
    user, _ = await register(client, "user", "v@x.test")
    await _shipment(Customer.model_validate(await Customer.get_motor_collection().find_one({})).id, "SHP1A2B3C4D5E")
    stages = []

    async def fake_stage(session, stage, detail=None):
        stages.append(stage)

    async def fake_stt(audio, filename):
        return "Where is my parcel S H P 1 A 2 B 3 C 4 D 5 E"

    async def fake_tts(text):
        return b"RIFF....WAVE" + b"\0" * 3000

    monkeypatch.setattr(pipeline, "emit_voice_stage", fake_stage)
    monkeypatch.setattr(pipeline, "transcribe_audio", fake_stt)
    monkeypatch.setattr(pipeline, "synthesize_speech", fake_tts)
    r = await client.post("/api/voice/chat", files={"audio": ("a.wav", b"x" * 100, "audio/wav")}, data={"sessionId": "s1"})
    assert r.status_code == 200, r.text
    body = r.json()
    # no Ollama in tests = LLM "down": the answer must still come from the database, labelled honestly
    assert body["agent"] == "tracking" and body["source"] == "builtin"
    assert "SHP1A2B3C4D5E" in body["reply"] and "out for delivery" in body["reply"]
    assert body["audioMimeType"] == "audio/wav" and body["audioBase64"]
    assert set(body["latencyMs"]) == {"stt", "llm", "tts", "total"}
    assert stages[0] == "transcribing" and "thinking" in stages and stages.index("transcribing") < stages.index("thinking")


async def test_misheard_id_is_repaired_only_from_the_callers_own_shipments(client):
    a, _ = await register(client, "user", "a@x.test")
    b, _ = await register(client, "user", "b@x.test")
    ca = await Customer.find_one(Customer.email == "a@x.test")
    cb = await Customer.find_one(Customer.email == "b@x.test")
    await _shipment(ca.id, "SHP1A2B3C4D5E")
    await _shipment(cb.id, "SHP9999999999")
    heard = "SHP182B3C4D5E"                                    # STT: "1A2" -> "182"
    mine = await execute_get_shipment_status(heard, current_user={"id": str(ca.id), "role": "user"})
    assert mine["found"] is False and mine["didYouMean"] == "SHP1A2B3C4D5E"
    other = await execute_get_shipment_status(heard, current_user={"id": str(cb.id), "role": "user"})
    assert "didYouMean" not in other                           # B must never be told A's tracking number
    anon = await execute_get_shipment_status(heard)
    assert "didYouMean" not in anon and anon["found"] is False  # tracking numbers are access tokens: no enumeration


async def test_voice_uses_a_tighter_llm_budget_than_chat(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_TIMEOUT_SECONDS", 30.0)
    assert ollama_client._timeout() == 30.0
    token = ollama_client.budget_override.set(8.0)
    try:
        assert ollama_client._timeout() == 8.0
    finally:
        ollama_client.budget_override.reset(token)
    assert ollama_client._timeout() == 30.0


# ─── hearing: transcript correction ──────────────────────────────────────
from voice.transcript_fix import fix_transcript  # noqa: E402


@pytest.mark.parametrize("heard,expected", [
    ("where is s h p one a two b three c four d five e", "SHP1A2B3C4D5E"),
    ("track shp one alpha two bravo three charlie four delta five echo", "SHP1A2B3C4D5E"),
    ("number is SHP182B3C4D5V", "SHP182B3C4D5E"),                      # V is not hex; it rhymes with E
    ("S. H. P. 1 A 2 B 3 C 4 D 5 E please", "SHP1A2B3C4D5E"),
])
def test_spelled_ids_are_repaired(heard, expected):
    assert expected in fix_transcript(heard)


@pytest.mark.parametrize("sentence", ["I have 5 parcels to send for two people", "what is my ship status", "where is my shp parcel",
                                      "call me at nine eight eight"])
def test_ordinary_speech_is_left_alone(sentence):
    assert fix_transcript(sentence) == sentence


def test_brand_words():
    assert fix_transcript("ship ora and ship bot") == "Shipora and ShipBot"


# ─── speaking: what the voice actually reads ─────────────────────────────
from services.tts import speech_text, trim_for_ear  # noqa: E402


def test_ids_money_units_are_spoken_not_symbolised():
    out = speech_text("Parcel **SHP1A2B3C4D5E** costs ₹1,250. It is 2.5 km, 3 kg. Rider KA01AB1234, call 98800 00001. ETA via UPI.")
    assert "S H P, 1 A 2, B 3 C, 4 D 5, E" in out
    assert "1250 rupees" in out and "₹" not in out
    assert "2.5 kilometres" in out and "3 kilograms" in out
    assert "K A, 0 1, A B 1 2 3 4" in out and "9 8 8 0 0, 0 0 0 0 1" in out
    assert "E T A" in out and "U P I" in out


def test_long_replies_are_cut_at_a_sentence_boundary():
    text = "First point is short. " * 40
    cut = trim_for_ear(text, 100)
    assert len(cut) <= 100 and cut.endswith(".")
    assert trim_for_ear("short", 100) == "short"


# ─── voice-friendly tracking numbers: SHP + 8 digits, last one a check digit ─
import re  # noqa: E402

from models.shipment import generate_tracking_number, tracking_checksum_ok  # noqa: E402


def test_new_tracking_numbers_are_short_digits_with_a_valid_check_digit():
    ids = {generate_tracking_number() for _ in range(300)}
    assert len(ids) > 295                                              # random, not sequential
    assert all(re.fullmatch(r"SHP[1-9][0-9]{7}", i) and tracking_checksum_ok(i) for i in ids)


def test_check_digit_catches_every_single_digit_error_and_most_swaps():
    t = generate_tracking_number()
    wrong = [t[:k] + str((int(t[k]) + d) % 10) + t[k + 1:] for k in range(3, 11) for d in range(1, 10)]
    assert not any(tracking_checksum_ok(w) for w in wrong)             # 72 single-digit mistakes, none slip through
    assert tracking_checksum_ok("SHP1A2B3C4D5E")                       # legacy IDs have no check digit and stay valid


@pytest.mark.parametrize("spoken", ["S H P 4 8 2 1 7 3 9 0", "shp 4821 7390", "SHP-4821-7390", "s h p four eight two one seven three nine zero"])
def test_spoken_new_format_variants(spoken):
    assert fix_transcript(f"where is {spoken} please").split()[2] == "SHP48217390"


def test_a_new_id_followed_by_words_is_not_swallowed_by_the_legacy_repair():
    assert fix_transcript("SHP48217390 is out for delivery") == "SHP48217390 is out for delivery"


async def test_bad_check_digit_is_rejected_without_a_database_lookup(client, monkeypatch):
    from models.shipment import Shipment
    calls = []
    real = Shipment.find_one
    monkeypatch.setattr(Shipment, "find_one", classmethod(lambda cls, *a, **k: (calls.append(1), real(*a, **k))[1]))
    good = generate_tracking_number()
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    out = await execute_get_shipment_status(bad)
    assert out["found"] is False and out["badChecksum"] is True and calls == []


async def test_bad_check_digit_on_a_voice_call_asks_for_a_repeat(client):
    from agents.tracking_agent import fallback
    good = generate_tracking_number()
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert "one digit at a time" in await fallback(f"where is {bad}")


@pytest.mark.parametrize("heard", ["SHPA80796550", "SH-P34846535", "shp 8079 6550", "S H P A 8 0 7 9 6 5 5 0"])
def test_asr_artifacts_around_the_prefix_are_tolerated(heard):
    got = extract_tracking_number(f"the tracking number is {heard}.")
    assert got and len(got) == 11 and got[3:].isdigit()


def test_a_real_word_after_shp_is_not_mistaken_for_an_artifact():
    assert extract_tracking_number("SHPAB1234567 is not a number") is None


@pytest.mark.parametrize("heard", ["track SHB 6071 7355", "track S H D 6 0 7 1 7 3 5 5", "SHT60717355", "shv-6071-7355"])
def test_a_rhyming_last_letter_of_the_prefix_is_repaired_when_eight_digits_follow(heard):
    assert extract_tracking_number(heard) == "SHP60717355"
    assert "SHP60717355" in fix_transcript(heard)


def test_a_rhyming_prefix_without_eight_digits_is_left_alone():
    assert extract_tracking_number("the SHB 1234 code") is None and fix_transcript("the SHB 1234 code") == "the SHB 1234 code"


def test_mangled_prefix_is_recovered_from_the_sentence_around_it():
    assert extract_tracking_number("Where is my parcel? The tracking number is as HP 81742801.") == "SHP81742801"
    assert extract_tracking_number("my order is 81742801") is None           # a bare number elsewhere is not a tracking number


async def test_a_dropped_digit_is_repaired_from_the_callers_own_shipments_only(client):
    await register(client, "user", "drop@x.test")
    await register(client, "user", "other@x.test")
    mine = await Customer.find_one(Customer.email == "drop@x.test")
    theirs = await Customer.find_one(Customer.email == "other@x.test")
    own, foreign = generate_tracking_number(), generate_tracking_number()
    await _shipment(mine.id, own)
    await _shipment(theirs.id, foreign)
    dropped = own[:5] + own[6:]                                               # one digit lost, as in "SHP-3591090"
    assert extract_tracking_number(f"the tracking number is {dropped}.") == dropped
    out = await execute_get_shipment_status(dropped, current_user={"id": str(mine.id), "role": "user"})
    assert out["didYouMean"] == own
    out = await execute_get_shipment_status(foreign[:5] + foreign[6:], current_user={"id": str(mine.id), "role": "user"})
    assert "didYouMean" not in out                                            # never suggests somebody else's parcel


def test_repeated_or_dropped_spoken_digits_are_never_guessed():
    # Parakeet-style output: digits as words, with the model stuttering a digit. 14 words != 8 digits -> do not truncate.
    stutter = "the tracking number is SHP one two four four four four four four eight nine four three one"
    def heard(t):                                        # what the pipeline does: correct the transcript, then extract
        return extract_tracking_number(fix_transcript(t))
    assert heard(stutter) is None
    assert heard("tracking number is S H P four eight two one seven three nine") is None      # only 7 digits
    assert heard("tracking number is S H P four eight two one seven three nine zero") == "SHP48217390"


def test_new_ids_are_spoken_in_two_groups_of_four():
    assert speech_text("Parcel SHP48217390 is out.") == "Parcel S H P, 4 8 2 1, 7 3 9 0 is out."
