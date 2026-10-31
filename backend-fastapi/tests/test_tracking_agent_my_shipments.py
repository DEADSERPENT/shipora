"""The tracking agent can find a logged-in customer's own parcels ("Where is my parcel?") without asking for a
tracking number, while an explicit tracking number still goes through get_shipment_status.

Gemini is faked (it only decides which tool to call and writes the closing text); the tracking agent, the real tool
executors and the database are real. Whether Gemini picks the right tool / handles one-vs-several shipments sensibly is
model behaviour and is checked live, not here."""
import pytest

import config
from agents import schedule_agent, tracking_agent
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio


@pytest.fixture
def gemini_calls(monkeypatch):
    """Fake Gemini: first call asks for `plan["tool"]` with `plan["args"]`; the plain-dict tool result is captured."""
    import google.generativeai as genai
    from types import SimpleNamespace

    plan, captured = {"tool": None, "args": {}}, {}

    class Model:
        def __init__(self, *a, **k): ...
        def generate_content(self, contents, tools=None, **kwargs):
            if tools is not None:
                part = SimpleNamespace(function_call=SimpleNamespace(name=plan["tool"], args=plan["args"]))
                return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
            return SimpleNamespace(text="final answer")

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", Model)
    monkeypatch.setattr(genai.protos, "FunctionResponse", lambda name, response: captured.update(name=name, result=dict(response)) or SimpleNamespace(name=name, response=response))
    monkeypatch.setattr(genai.protos, "Part", lambda function_response=None, **k: SimpleNamespace(function_response=function_response))
    return plan, captured


async def make_shipment(client, headers, label):
    r = await client.post("/api/shipments", json={"recipient": {**RECIPIENT, "name": label}, "parcel": {"description": label}}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    return (body.get("shipment") or body)["trackingNumber"]


def test_tracking_agent_offers_all_three_tools_and_the_schedule_agent_is_unchanged():
    import inspect

    src = inspect.getsource(tracking_agent.handle)
    for name in ("get_vehicle_status", "get_shipment_status", "get_my_shipments"):
        assert f'"{name}"' in src
    assert "partial(execute_get_my_shipments, current_user=current_user)" in src          # bound to the caller
    assert "TOOL_GET_MY_SHIPMENTS" in inspect.getsource(schedule_agent.handle)             # schedule agent keeps its tool


def test_prompt_tells_the_model_how_to_handle_one_several_and_no_active_shipments():
    p = tracking_agent.SYSTEM_PROMPT
    assert "get_my_shipments" in p and "get_shipment_status" in p and "isActive" in p
    assert "exactly one" in p and "ask which one" in p and "not logged in" in p.replace("aren't logged in", "not logged in")


async def test_my_parcels_returns_only_the_callers_shipments_with_active_flags(client, gemini_calls):
    plan, captured = gemini_calls
    a, ha = await register(client, "user", "a@t.test")
    b, hb = await register(client, "user", "b@t.test")
    active = await make_shipment(client, ha, "A-active")
    cancelled = await make_shipment(client, ha, "A-cancelled")
    assert (await client.post(f"/api/shipments/{cancelled}/status", json={"status": "CANCELLED"}, headers=ha)).status_code == 200
    others = await make_shipment(client, hb, "B-secret")

    plan.update(tool="get_my_shipments", args={})
    reply = await tracking_agent.handle("Where is my parcel?", [], "neutral", current_user={"id": a["id"], "role": "user"})

    assert reply == "final answer" and captured["name"] == "get_my_shipments"
    got = {s["trackingNumber"]: s for s in captured["result"]["shipments"]}
    assert set(got) == {active, cancelled} and others not in got                           # never another customer's parcel
    assert got[active]["isActive"] is True and got[cancelled]["isActive"] is False
    assert got[active]["status"] == "CREATED" and got[active]["estimatedDelivery"]         # enough to answer without a second lookup


async def test_customers_cannot_see_each_others_shipments_even_if_the_model_asks_for_someone_else(client, gemini_calls):
    plan, captured = gemini_calls
    a, ha = await register(client, "user", "a2@t.test")
    b, hb = await register(client, "user", "b2@t.test")
    await make_shipment(client, ha, "A-one")
    b_tn = await make_shipment(client, hb, "B-one")
    plan.update(tool="get_my_shipments", args={"customerId": b["id"]})                    # a hallucinated/injected argument
    try:
        await tracking_agent.handle("show shipments of the other customer", [], "neutral", current_user={"id": a["id"], "role": "user"})
    except TypeError:
        pass                                                                               # the tool has no such parameter: rejected, not honoured
    assert b_tn not in str(captured.get("result", ""))


@pytest.mark.parametrize("user", [None, {"id": "000000000000000000000000", "role": "driver"}, {"id": "000000000000000000000000", "role": "admin"}])
async def test_not_a_logged_in_customer_gets_a_note_not_data(client, gemini_calls, user):
    plan, captured = gemini_calls
    c, hc = await register(client, "user", "c@t.test")
    await make_shipment(client, hc, "C-one")
    plan.update(tool="get_my_shipments", args={})
    await tracking_agent.handle("Where is my parcel?", [], "neutral", current_user=user)
    assert "shipments" not in captured["result"] and "log in" in captured["result"]["note"]


async def test_explicit_tracking_number_still_uses_get_shipment_status(client, gemini_calls):
    plan, captured = gemini_calls
    c, hc = await register(client, "user", "d@t.test")
    tn = await make_shipment(client, hc, "D-one")
    plan.update(tool="get_shipment_status", args={"trackingNumber": tn})
    await tracking_agent.handle(f"Where is shipment {tn}?", [], "neutral", current_user={"id": c["id"], "role": "user"})
    assert captured["name"] == "get_shipment_status"
    assert captured["result"].get("trackingNumber") == tn or tn in str(captured["result"])
