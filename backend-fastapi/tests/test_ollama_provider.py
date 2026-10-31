"""The Ollama LLM provider, exercised against a fake Ollama so it runs anywhere. The real GPU run is
scripts/verify_sandwich.py against a live `ollama serve`."""
import json

import httpx
import pytest

import config
from agents import orchestrator
from services import ollama_client
from tests.test_voice_sandwich import _shipment
from tests.conftest import register
from models.customer import Customer

pytestmark = pytest.mark.anyio


class FakeOllama:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        ollama_client._transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        step = self.script.pop(0)
        if isinstance(step, int):
            return httpx.Response(step)
        return httpx.Response(200, json={"message": step})


async def test_classifier_uses_a_json_schema_and_returns_a_valid_agent():
    fake = FakeOllama([{"role": "assistant", "content": '{"agent": "complaints", "sentiment": "negative"}'}])
    assert await orchestrator.classify("my parcel is broken", []) == {"agent": "complaints", "sentiment": "negative"}
    assert fake.requests[0]["format"]["properties"]["agent"]["enum"] == ["tracking", "complaints", "schedule", "support", "general"]
    assert fake.requests[0]["options"]["temperature"] == 0 and fake.requests[0]["stream"] is False


async def test_bad_classifier_output_falls_back_to_keywords():
    FakeOllama([{"role": "assistant", "content": '{"agent": "banana", "sentiment": "neutral"}'}])
    assert (await orchestrator.classify("where is my parcel", []))["agent"] == "tracking"
    FakeOllama([500])
    assert (await orchestrator.classify("contact details for customer care", []))["agent"] == "support"


async def test_tool_loop_runs_the_tool_and_answers_from_its_result(client):
    await register(client, "user", "o@x.test")
    cust = await Customer.find_one(Customer.email == "o@x.test")
    await _shipment(cust.id, "SHP1A2B3C4D5E", "IN_TRANSIT")
    fake = FakeOllama([
        {"role": "assistant", "content": '{"agent": "tracking", "sentiment": "neutral"}'},                       # classifier
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_shipment_status", "arguments": {"trackingNumber": "SHP1A2B3C4D5E"}}}]},
        {"role": "assistant", "content": "Your parcel SHP1A2B3C4D5E is in transit."},
    ])
    stages = []
    result = await orchestrator.route_and_reply("where is SHP1A2B3C4D5E", [], None, on_stage=lambda s, d=None: stages.append(s))
    assert result["reply"] == "Your parcel SHP1A2B3C4D5E is in transit." and result["agent"] == "tracking" and result["source"] == "ai"
    assert len(fake.requests) == 3                                     # classifier + tool request + final answer
    final_call = fake.requests[-1]
    tool_msg = next(m for m in final_call["messages"] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["status"] == "IN_TRANSIT"   # the model was shown the database's answer
    assert "tools" not in final_call                                   # the second call must answer in text
    assert "tool_execution" in stages and "generating_response" in stages


async def test_ollama_down_still_answers_tracking_from_the_database(client):
    await register(client, "user", "o2@x.test")
    cust = await Customer.find_one(Customer.email == "o2@x.test")
    await _shipment(cust.id, "SHP1A2B3C4D5E", "OUT_FOR_DELIVERY")
    ollama_client._transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    result = await orchestrator.route_and_reply("where is SHP1A2B3C4D5E", [], None)
    assert result["source"] == "builtin" and "out for delivery" in result["reply"]


async def test_qwen3_thinking_is_switched_off(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen3:8b")
    fake = FakeOllama([{"role": "assistant", "content": "hi"}])
    await ollama_client.chat([{"role": "user", "content": "x"}])
    assert fake.requests[0]["think"] is False
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen2.5:3b")
    fake = FakeOllama([{"role": "assistant", "content": "hi"}])
    await ollama_client.chat([{"role": "user", "content": "x"}])
    assert "think" not in fake.requests[0]


# ── audit regressions: what a small model can do wrong inside the tool loop ──
async def _tracking_turn(client, email, script):
    await register(client, "user", email)
    cust = await Customer.find_one(Customer.email == email)
    await _shipment(cust.id, "SHP1A2B3C4D5E", "IN_TRANSIT")
    fake = FakeOllama([{"role": "assistant", "content": '{"agent": "tracking", "sentiment": "neutral"}'}, *script])
    return fake, await orchestrator.route_and_reply("where is SHP1A2B3C4D5E", [], None)


@pytest.mark.parametrize("leak", [
    '[{"type":"function","function":{"name":"get_shipment_status","description":"x","parameters":{}}}]',
    '{"name": "get_shipment_status", "arguments": {"trackingNumber": "SHP1A2B3C4D5E"}}',
])
async def test_a_tool_call_leaked_as_text_is_never_shown_and_the_database_answers(client, leak):
    _, result = await _tracking_turn(client, "leak@x.test", [{"role": "assistant", "content": leak}])
    assert "function" not in result["reply"] and "{" not in result["reply"]
    assert "IN TRANSIT" in result["reply"].upper().replace("_", " ") and result["source"] == "builtin"


async def test_malformed_or_invented_tool_arguments_do_not_crash_the_turn(client):
    call = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_shipment_status", "arguments": {"bogus": 1}}},
                                                                 {"function": {"name": "get_shipment_status", "arguments": "{not json"}},
                                                                 {"function": {"name": "does_not_exist", "arguments": {}}}]}
    fake, result = await _tracking_turn(client, "bad@x.test", [call, {"role": "assistant", "content": "Sorry, I could not look that up."}])
    tool_msgs = [m for m in fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 2                                         # at most two tool calls per turn
    assert all("error" in json.loads(m["content"]) for m in tool_msgs)
    assert "SHP1A2B3C4D5E" in result["reply"] and "in transit" in result["reply"] and result["source"] == "builtin"   # the model could not look it up; the database can


async def test_a_hanging_tool_times_out_instead_of_hanging_the_turn(monkeypatch):
    import asyncio
    monkeypatch.setattr(ollama_client, "TOOL_TIMEOUT_SECONDS", 0.05)

    async def hang(**kw):
        await asyncio.sleep(5)
    FakeOllama([{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "slow", "arguments": {}}}]}])
    tool = {"name": "slow", "description": "d", "input_schema": {"type": "object", "properties": {}}}
    with pytest.raises(RuntimeError, match="timed out"):          # base.py turns this into the normal database fallback
        await ollama_client.run_tool_agent("sys", [tool], {"slow": hang}, "hi", [], "neutral")


# ── capability guards found by scripts/eval_ollama.py on the real model ──
def test_a_repetition_loop_is_not_an_answer():
    assert ollama_client.degenerate("ಪ್ರತಿನಿಧಿಯನ್ನು ತಿಳಿಸಲ್ಪಟು ಹಾಗೂ ಮಾನವಿಕ ಸ್ಥಳದ " * 12)
    assert not ollama_client.degenerate("Your parcel SHP48217390 is out for delivery and should arrive on Monday, 12 October 2026.")
    assert not ollama_client.degenerate("short")


async def test_a_looping_reply_falls_back_to_the_database_answer(client):
    await register(client, "user", "loop@x.test")
    cust = await Customer.find_one(Customer.email == "loop@x.test")
    await _shipment(cust.id, "SHP1A2B3C4D5E", "IN_TRANSIT")
    loop = " ".join(["ಮತ್ತು ಮಾನವಿಕ ಸ್ಥಳದ ಪ್ರಾರೂಧಿ ತಿಳಿಸಲ್ಪಟು"] * 12)
    FakeOllama([{"role": "assistant", "content": '{"agent": "tracking", "sentiment": "neutral"}'},
                {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_shipment_status", "arguments": {"trackingNumber": "SHP1A2B3C4D5E"}}}]},
                {"role": "assistant", "content": loop}])
    result = await orchestrator.route_and_reply("where is SHP1A2B3C4D5E", [], None)
    assert "SHP1A2B3C4D5E" in result["reply"] and result["source"] == "builtin"


async def test_a_model_that_chats_about_a_problem_still_gets_it_drafted_for_confirmation(client):
    from models.complaint_draft import ComplaintDraft
    u, _ = await register(client, "user", "dmg@x.test")
    cust = await Customer.find_one(Customer.email == "dmg@x.test")
    await _shipment(cust.id, "SHP1A2B3C4D5E", "DELIVERED")
    user = {"id": str(cust.id), "role": "user", "name": "c", "email": "dmg@x.test"}
    FakeOllama([
        {"role": "assistant", "content": '{"agent": "complaints", "sentiment": "negative"}'},                      # classifier
        {"role": "assistant", "content": "I'm sorry to hear that. Please confirm if this matches the issue."},      # model chats, no tool call
        {"role": "assistant", "content": '{"is_report": true, "subject": "Damaged parcel", "category": "damaged_parcel", '
                                         '"description": "The box was crushed.", "trackingNumber": "SHP1A2B3C4D5E"}'},   # structured extraction
    ])
    out = await orchestrator.route_and_reply("My parcel SHP1A2B3C4D5E arrived damaged, the box was crushed", [], user, session_id="s-dmg")
    assert "nothing is filed yet" in out["reply"].lower() and "Damaged parcel" in out["reply"]
    d = await ComplaintDraft.find_one(ComplaintDraft.userId == str(cust.id))
    assert d and d.status == "pending" and d.category == "damaged_parcel"


async def test_a_status_question_is_not_mistaken_for_a_report(client):
    from models.complaint_draft import ComplaintDraft
    await register(client, "user", "st@x.test")
    cust = await Customer.find_one(Customer.email == "st@x.test")
    user = {"id": str(cust.id), "role": "user", "name": "c", "email": "st@x.test"}
    FakeOllama([{"role": "assistant", "content": '{"agent": "complaints", "sentiment": "neutral"}'},
                {"role": "assistant", "content": "You have no issues on file."}])
    out = await orchestrator.route_and_reply("What's the status of my complaints about late deliveries?", [], user, session_id="s-st")
    assert out["reply"] == "You have no delivery issues on file." and await ComplaintDraft.find_all().count() == 0   # the database answers; nothing is drafted


async def test_a_riders_route_is_answered_exactly_from_the_database_without_a_model(client):
    import httpx as _h
    ollama_client._transport = _h.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("the model must not be called")))
    d, _ = await register(client, "driver", "rt@x.test")
    from models.shipment import Shipment
    await register(client, "user", "rt-c@x.test")
    cust = await Customer.find_one(Customer.email == "rt-c@x.test")
    from beanie import PydanticObjectId
    s = await _shipment(cust.id, "SHP1A2B3C4D5E", "OUT_FOR_DELIVERY")
    s.assignedAgentId = PydanticObjectId(d["id"])
    await s.save()
    out = await orchestrator.route_and_reply("What's on my route today?", [], {"id": d["id"], "role": "driver"})
    assert "SHP1A2B3C4D5E" in out["reply"] and out["source"] == "builtin" and out["agent"] == "tracking"


async def test_complaint_status_is_answered_from_the_database_when_the_model_only_promises(client):
    from tools.complaint_tools import insert_complaint
    await register(client, "user", "cs@x.test")
    cust = await Customer.find_one(Customer.email == "cs@x.test")
    user = {"id": str(cust.id), "role": "user", "name": "c", "email": "cs@x.test"}
    await insert_complaint("Damaged parcel", "damaged_parcel", "Box crushed", False, user, None)
    FakeOllama([{"role": "assistant", "content": '{"agent": "complaints", "sentiment": "neutral"}'},
                {"role": "assistant", "content": "Sure, let me check the status of your complaints for you."}])      # a promise, no tool call
    out = await orchestrator.route_and_reply("What's the status of my complaints?", [], user, session_id="s-cs")
    assert "Damaged parcel" in out["reply"] and "open" in out["reply"] and out["source"] == "builtin" and out["agent"] == "complaints"


async def test_complaint_status_still_works_with_ollama_down(client):
    from tools.complaint_tools import insert_complaint
    await register(client, "user", "cs2@x.test")
    cust = await Customer.find_one(Customer.email == "cs2@x.test")
    user = {"id": str(cust.id), "role": "user", "name": "c", "email": "cs2@x.test"}
    await insert_complaint("Late delivery", "delayed_delivery", "Two days late", False, user, None)
    out = await orchestrator.route_and_reply("What's the status of my complaints?", [], user, session_id="s-cs2")   # conftest: Ollama is unreachable
    assert "Late delivery" in out["reply"] and out["source"] == "builtin"


@pytest.mark.parametrize("question", ["Can I cancel my shipment after booking it?", "How do I change the address of my parcel?", "What if my order is not delivered?"])
async def test_a_policy_question_about_my_shipment_is_not_answered_with_a_shipment_list(client, question):
    await register(client, "user", "pol@x.test")
    cust = await Customer.find_one(Customer.email == "pol@x.test")
    await _shipment(cust.id, "SHP1A2B3C4D5E", "IN_TRANSIT")
    user = {"id": str(cust.id), "role": "user", "name": "c", "email": "pol@x.test"}
    FakeOllama([{"role": "assistant", "content": '{"agent": "general", "sentiment": "neutral"}'},
                {"role": "assistant", "content": "Yes, you can cancel from the shipment page until the parcel is picked up."}])
    out = await orchestrator.route_and_reply(question, [], user)
    assert "SHP1A2B3C4D5E" not in out["reply"] and out["agent"] == "general"


# ── support contact details must be Shipora's, never invented ──
def test_invented_contact_details_are_detected_and_real_ones_are_not():
    from agents.support_agent import invents_contact_details
    cfg = {"phone": "1800-SHIPORA", "email": "support@shipora.in", "whatsapp": "+91 98765 43210", "officeHours": "Mon – Fri · 9 AM – 5 PM", "officeAddress": "Hub"}
    assert invents_contact_details("Call 123-456-7890 or email support@shipora.com", cfg)
    assert invents_contact_details("WhatsApp us on +1234567890", cfg)
    assert not invents_contact_details("Email support@shipora.in or WhatsApp +91 98765 43210, or call 1800-SHIPORA.", cfg)
    assert not invents_contact_details("Delivery starts at ₹48 for the first 1 km.", cfg)


async def test_a_made_up_support_number_is_replaced_with_the_real_contact_details(client):
    FakeOllama([{"role": "assistant", "content": '{"agent": "support", "sentiment": "neutral"}'},
                {"role": "assistant", "content": "Call us at 123-456-7890 or email support@shipora.com, 9 AM to 5 PM."}])
    out = await orchestrator.route_and_reply("What are your support hours and phone number?", [], None)
    assert "123-456-7890" not in out["reply"] and "1800-SHIPORA" in out["reply"] and "support@shipora.in" in out["reply"] and out["source"] == "builtin"


@pytest.mark.parametrize("question,contact", [("Can I cancel my shipment after booking it?", False), ("How much does delivery cost?", False),
                                              ("What are your support hours and phone number?", True), ("How can I contact customer care?", True)])
async def test_only_contact_questions_reach_the_support_specialist(client, question, contact):
    fake = FakeOllama([{"role": "assistant", "content": '{"agent": "support", "sentiment": "neutral"}'},     # a classifier that always says support
                       {"role": "assistant", "content": "ok"}])
    out = await orchestrator.route_and_reply(question, [], None)
    assert (out["agent"] == "support") == contact or (contact and out["agent"] == "general" and out["source"] == "builtin")
