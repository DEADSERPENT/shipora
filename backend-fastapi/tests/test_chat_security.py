"""Authorization is enforced inside every sensitive executor and in every fallback path, not only by which tools the model is
offered. Nothing here depends on a model behaving."""
from datetime import datetime

import pytest

from agents import general_agent, orchestrator, tracking_agent
from models.tracking_log import TrackingLog
from tests.conftest import register
from tests.test_tracking_agent_my_shipments import gemini_calls, make_shipment  # noqa: F401  (fixture re-export)
from tools.analytics import execute_get_operations_summary
from tools.shipment_tools import execute_get_shipment_status
from tools.tracking_tools import execute_get_vehicle_status
from utils.dates import today_string

pytestmark = pytest.mark.anyio

CUSTOMER = {"id": "0" * 24, "role": "user"}
RIDER = {"id": "1" * 24, "role": "driver"}
ADMIN = {"id": "2" * 24, "role": "admin"}


async def fleet_world(client):
    """Two riders, a shipment assigned to each, an admin, and one live vehicle log."""
    _, ch = await register(client, "user", "sec-cust@t.test")
    a, ah = await register(client, "driver", "sec-a@t.test", vehicleNo="KA01AA0001")
    b, _ = await register(client, "driver", "sec-b@t.test", vehicleNo="KA01BB0002")
    _, adm = await register(client, "admin", "sec-admin@t.test")
    tn_a = await make_shipment(client, ch, "for-a")
    tn_b = await make_shipment(client, ch, "for-b")
    sid = {s["trackingNumber"]: s["_id"] for s in (await client.get("/api/shipments", headers=adm)).json()}
    for tn, rider in ((tn_a, a), (tn_b, b)):
        assert (await client.put(f"/api/shipments/{sid[tn]}/assign", json={"agentId": rider["id"]}, headers=adm)).status_code == 200
    from beanie import PydanticObjectId
    await TrackingLog(driverId=PydanticObjectId(a["id"]), date=today_string(), lat=12.9, lng=77.6, currentArea="Koramangala",
                      eta="10 mins", areasCompleted=[], lastUpdated=datetime.utcnow(), isActive=True).insert()
    return {"a": {"id": a["id"], "role": "driver"}, "b": {"id": b["id"], "role": "driver"}, "tn_a": tn_a, "tn_b": tn_b}


# ── sensitive executors check the caller themselves ─────────────────────────
@pytest.mark.parametrize("user", [None, CUSTOMER, RIDER])
async def test_vehicle_status_executor_refuses_everyone_but_operations(client, user):
    await fleet_world(client)
    out = await execute_get_vehicle_status(area="Koramangala", current_user=user)
    assert not out.get("vehicles") and out.get("note")
    assert "KA01AA0001" not in str(out) and "Agent" not in str(out)


async def test_vehicle_status_executor_serves_operations(client):
    await fleet_world(client)
    out = await execute_get_vehicle_status(area="Koramangala", current_user=ADMIN)
    assert out["vehicles"][0]["vehicleNo"] == "KA01AA0001"


@pytest.mark.parametrize("user", [None, CUSTOMER, RIDER])
async def test_operations_summary_executor_refuses_everyone_but_operations(client, user):
    await fleet_world(client)
    out = await execute_get_operations_summary(current_user=user)
    assert "shipments" not in out and "complaints" not in out and out.get("note")


async def test_operations_summary_executor_serves_operations_and_names_its_period(client):
    await fleet_world(client)
    out = await execute_get_operations_summary(days=7, current_user=ADMIN)
    assert out["shipments"]["total"] == 2 and out["windowDays"] == 7 and "last 7 days" in out["periodText"]
    assert "all time" in out["shipmentsPeriodText"]


# ── a rider only ever sees their own shipments ──────────────────────────────
async def test_rider_cannot_look_up_another_riders_shipment_in_the_executor(client):
    w = await fleet_world(client)
    other = await execute_get_shipment_status(w["tn_b"], current_user=w["a"])
    assert other["found"] is False and "status" not in other and "timeline" not in other and "not assigned" in other["note"]
    mine = await execute_get_shipment_status(w["tn_a"], current_user=w["a"])
    assert mine["found"] is True and mine["trackingNumber"] == w["tn_a"]


async def test_a_nonexistent_number_is_indistinguishable_from_someone_elses_for_a_rider(client):
    w = await fleet_world(client)
    ghost = await execute_get_shipment_status("SHP00000000", current_user=w["a"])
    theirs = await execute_get_shipment_status(w["tn_b"], current_user=w["a"])
    assert ghost["found"] is False and theirs["found"] is False        # a rider cannot probe which numbers exist


# ── fallbacks: the model is down, the rules answer, the rules obey the same authorization ─
@pytest.fixture
def model_down(monkeypatch):
    async def classify(message, history):
        return {"agent": "tracking", "sentiment": "neutral"}

    async def none(*a, **k):
        return None
    monkeypatch.setattr(orchestrator, "classify", classify)
    monkeypatch.setattr(tracking_agent, "run_tool_agent", none)
    monkeypatch.setattr(general_agent, "run_tool_agent", none)

    async def no_llm(*a, **k):
        return None
    monkeypatch.setattr(general_agent, "get_llm_reply", no_llm)


async def test_fallback_never_reveals_another_riders_shipment(client, model_down):
    w = await fleet_world(client)
    out = await orchestrator.route_and_reply(f"Where is shipment {w['tn_b']}?", [], w["a"])
    assert out["source"] == "builtin"
    assert "not assigned" in out["reply"].lower() or "isn't assigned" in out["reply"].lower()
    for leak in ("out for delivery", "pickup scheduled", "estimated", "currently"):
        assert leak not in out["reply"].lower()


async def test_fallback_still_serves_a_riders_own_shipment(client, model_down):
    w = await fleet_world(client)
    out = await orchestrator.route_and_reply(f"Where is shipment {w['tn_a']}?", [], w["a"])
    assert w["tn_a"] in out["reply"] and "currently" in out["reply"]


async def test_fallback_lists_a_riders_assignments_from_the_database(client, model_down):
    w = await fleet_world(client)
    out = await orchestrator.route_and_reply("What's on my route today?", [], w["a"])
    assert w["tn_a"] in out["reply"] and w["tn_b"] not in out["reply"]


@pytest.mark.parametrize("who", [None, CUSTOMER, RIDER])
async def test_fallback_gives_no_fleet_or_operations_data_to_anyone_but_operations(client, model_down, who):
    await fleet_world(client)
    for q in ("Which vehicles are live right now?", "Summarize today's operations"):
        out = await orchestrator.route_and_reply(q, [], who)
        text = out["reply"]
        assert "KA01AA0001" not in text and "Koramangala" not in text and "byStatus" not in text
        assert not any(ch.isdigit() for ch in text.replace("24/7", "")) or "operations accounts only" in text.lower() or "operations only" in text.lower()


async def test_a_model_hallucinating_a_forbidden_tool_gets_nothing(client, gemini_calls):
    plan, captured = gemini_calls
    await fleet_world(client)
    plan.update(tool="get_vehicle_status", args={})
    reply = await tracking_agent.handle("which vehicles are live", [], "neutral", current_user=CUSTOMER)
    assert reply is None and "vehicles" not in captured.get("result", {})           # executor not even bound; turn falls back


# ── an outage still serves the common questions from the database, to the right person only ──
async def test_with_the_model_down_a_rider_still_gets_their_route_even_when_the_classifier_is_the_keyword_one(client, monkeypatch):
    from agents import tracking_agent as ta
    w = await fleet_world(client)

    async def none(*a, **k):
        return None
    for mod in (ta, general_agent):
        monkeypatch.setattr(mod, "run_tool_agent", none)
    monkeypatch.setattr(general_agent, "get_llm_reply", none)

    async def keyword_general(message, history):
        return {"agent": "general", "sentiment": "neutral"}          # what the zero-key keyword router says for this sentence
    monkeypatch.setattr(orchestrator, "classify", keyword_general)
    out = await orchestrator.route_and_reply("What's on my route today?", [], w["a"])
    assert w["tn_a"] in out["reply"] and w["tn_b"] not in out["reply"] and out["agent"] == "tracking"


async def test_with_the_model_down_a_customer_still_sees_their_own_parcels_and_nobody_elses(client, monkeypatch):
    from agents import tracking_agent as ta
    from tests.conftest import register
    _, ch = await register(client, "user", "outage-c@t.test")
    other_u, oh = await register(client, "user", "outage-o@t.test")
    mine = await make_shipment(client, ch, "mine")
    theirs = await make_shipment(client, oh, "theirs")
    me = (await client.get("/api/auth/me", headers=ch)).json() if False else None   # noqa
    from models.customer import Customer
    cust = await Customer.find_one(Customer.email == "outage-c@t.test")

    async def none(*a, **k):
        return None
    for mod in (ta, general_agent):
        monkeypatch.setattr(mod, "run_tool_agent", none)
    monkeypatch.setattr(general_agent, "get_llm_reply", none)

    async def keyword_general(message, history):
        return {"agent": "general", "sentiment": "neutral"}
    monkeypatch.setattr(orchestrator, "classify", keyword_general)
    out = await orchestrator.route_and_reply("Where is my parcel?", [], {"id": str(cust.id), "role": "user"})
    assert mine in out["reply"] and theirs not in out["reply"]
