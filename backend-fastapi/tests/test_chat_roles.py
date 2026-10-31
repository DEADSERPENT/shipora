"""ShipBot is role-aware on the server: the profile the widget renders, which specialists each role reaches, and which
data tools each role is offered. Gemini is faked; routing, tools and database are real."""
import pytest

from agents import orchestrator, roles, tracking_agent, general_agent
from tests.conftest import register
from tests.test_tracking_agent_my_shipments import gemini_calls, make_shipment  # noqa: F401  (fixture re-export)

pytestmark = pytest.mark.anyio


async def test_profile_differs_per_role(client):
    seen = {}
    anon = (await client.get("/api/chat/profile")).json()
    seen["anonymous"] = anon
    for kind in ("user", "driver", "admin"):
        _, h = await register(client, kind, f"{kind}-profile@t.test")
        seen[kind] = (await client.get("/api/chat/profile", headers=h)).json()
    assert {k: v["role"] for k, v in seen.items()} == {k: k for k in seen}
    texts = {k: tuple(s["text"] for s in v["suggestions"]) for k, v in seen.items()}
    assert len(set(texts.values())) == 4                                   # four roles, four different sets
    assert any("route" in t.lower() for t in texts["driver"])
    assert any("operations" in t.lower() for t in texts["admin"])
    assert any("my parcel" in t.lower() for t in texts["user"])


def test_each_role_only_reaches_its_specialists():
    rider, admin, customer = {"role": "driver"}, {"role": "admin"}, {"role": "user"}
    assert roles.route_for(rider, "complaints")[1]                         # denied with an explanation
    assert roles.route_for(rider, "schedule") == ("tracking", None)       # a rider's "schedule" is their assignments
    assert roles.route_for(admin, "schedule") == ("tracking", None)
    assert roles.route_for(admin, "complaints") == ("complaints", None)
    assert roles.route_for(customer, "complaints") == ("complaints", None)


async def test_driver_asking_to_file_an_issue_is_told_who_does_that(client, monkeypatch):
    async def fake_classify(message, history):
        return {"agent": "complaints", "sentiment": "neutral"}
    monkeypatch.setattr(orchestrator, "classify", fake_classify)
    out = await orchestrator.route_and_reply("file a complaint", [], {"id": "0" * 24, "role": "driver"})
    assert "Operations" in out["reply"] and out["source"] == "builtin"


async def test_driver_sees_only_their_own_assignments(client, gemini_calls):
    plan, captured = gemini_calls
    _, ch = await register(client, "user", "cust-r@t.test")
    mine, ah = await register(client, "driver", "rider-mine@t.test")
    other, _ = await register(client, "driver", "rider-other@t.test")
    _, adm = await register(client, "admin", "ops-r@t.test")
    tn_mine = await make_shipment(client, ch, "for-mine")
    tn_other = await make_shipment(client, ch, "for-other")
    for tn, agent in ((tn_mine, mine), (tn_other, other)):
        sid = (await client.get(f"/api/shipments/track/{tn}")).json()
        full = [s for s in (await client.get("/api/shipments", headers=adm)).json() if s["trackingNumber"] == tn][0]
        assert (await client.put(f"/api/shipments/{full['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)).status_code == 200

    user = {"id": mine["id"], "role": "driver"}
    plan.update(tool="get_my_assignments", args={})
    await tracking_agent.handle("what's on my route", [], "neutral", current_user=user)
    got = {s["trackingNumber"] for s in captured["result"]["shipments"]}
    assert got == {tn_mine}

    plan.update(tool="get_shipment_status", args={"trackingNumber": tn_other})            # someone else's parcel
    await tracking_agent.handle(f"where is {tn_other}", [], "neutral", current_user=user)
    assert captured["result"]["found"] is False and "not assigned" in captured["result"]["note"]

    plan.update(tool="get_shipment_status", args={"trackingNumber": tn_mine})
    await tracking_agent.handle(f"where is {tn_mine}", [], "neutral", current_user=user)
    assert captured["result"]["found"] is True


async def test_tools_offered_depend_on_the_role(monkeypatch):
    offered = {}

    async def spy(system, tools, executors, *a, **k):
        offered["tools"] = {t["name"] for t in tools}
        offered["system"] = system
        return "ok"
    monkeypatch.setattr(tracking_agent, "run_tool_agent", spy)
    monkeypatch.setattr(general_agent, "run_tool_agent", spy)

    await tracking_agent.handle("x", [], "neutral", current_user={"id": "0" * 24, "role": "user"})
    assert "get_vehicle_status" not in offered["tools"] and "get_my_shipments" in offered["tools"]
    await tracking_agent.handle("x", [], "neutral", current_user={"id": "0" * 24, "role": "driver"})
    assert offered["tools"] == {"get_my_assignments", "get_shipment_status"} and "DELIVERY AGENT" in offered["system"]
    await tracking_agent.handle("x", [], "neutral", current_user={"id": "0" * 24, "role": "admin"})
    assert offered["tools"] == {"get_vehicle_status", "get_shipment_status"} and "OPERATIONS" in offered["system"]

    await general_agent.handle("x", [], "neutral", current_user={"id": "0" * 24, "role": "user"})
    assert "get_operations_summary" not in offered["tools"]                # company-wide numbers are admin-only
    await general_agent.handle("x", [], "neutral", current_user={"id": "0" * 24, "role": "admin"})
    assert "get_operations_summary" in offered["tools"]


def test_ops_numbers_and_fleet_questions_are_refused_before_any_model_runs():
    cust, rider, admin = {"role": "user"}, {"role": "driver"}, {"role": "admin"}
    for who in (None, cust, rider):
        assert roles.intent_denial(who, "Summarize today's operations")
    assert roles.intent_denial(admin, "Summarize today's operations") is None
    assert roles.intent_denial(rider, "Which vehicles are live right now?")
    assert roles.intent_denial(rider, "What's on my route today?") is None
    assert roles.intent_denial(cust, "Where is my parcel?") is None


def test_only_a_short_unambiguous_yes_counts_as_confirmation():
    from services.complaint_drafts import classify_reply
    for yes in ("yes", "Yes please", "go ahead", "yeah", "file it", "ok"):
        assert classify_reply(yes) == "confirm", yes
    for no in ("no", "No thanks", "cancel", "don't"):
        assert classify_reply(no) == "decline", no
    for other in ("hmm maybe", "yes but make it urgent", "my parcel is damaged", "what does that mean", "yes and also add that it was raining"):
        assert classify_reply(other) == "other", other
