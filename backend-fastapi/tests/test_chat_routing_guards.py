"""Found by running the whole assistant end to end against a real small model: routing and argument problems that unit tests of the
individual agents could not see. The classifier is made to misbehave on purpose; the guards must still hold."""
import pytest

from agents import complaints_agent, orchestrator, roles, tracking_agent
from models.complaint_draft import ComplaintDraft
from models.delivery_issue import DeliveryIssue
from tests.test_complaint_confirmation import ARGS, customer, draft, model, say  # noqa: F401  (fixtures + helpers)

pytestmark = pytest.mark.anyio


@pytest.fixture
def classifier_says(monkeypatch):
    def use(agent):
        async def classify(message, history):
            return {"agent": agent, "sentiment": "neutral"}
        monkeypatch.setattr(orchestrator, "classify", classify)
    return use


async def turn(user, message, session="s1"):
    return await orchestrator.route_and_reply(message, [], user, session_id=session)


async def test_a_yes_to_a_pending_draft_reaches_the_confirmation_whatever_the_classifier_thinks(client, model, classifier_says):
    u, _ = await customer(client, "g1@t.test")
    await draft(model, u)
    model.update(tool=None, called=0)
    classifier_says("tracking")                                       # a small model files "yes" under tracking
    out = await turn(u, "yes")
    assert await DeliveryIssue.find_all().count() == 1 and "filed" in out["reply"].lower() and out["agent"] == "complaints"
    again = await turn(u, "yes")
    assert await DeliveryIssue.find_all().count() == 1 and "already" in again["reply"].lower()


async def test_a_no_to_a_pending_draft_cancels_it_whatever_the_classifier_thinks(client, model, classifier_says):
    u, _ = await customer(client, "g2@t.test")
    await draft(model, u)
    classifier_says("general")
    out = await turn(u, "no")
    assert "haven't filed" in out["reply"].lower()
    assert (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).status == "declined"


async def test_a_bare_yes_or_no_with_nothing_pending_never_lets_the_model_draft_something(client, model, classifier_says):
    u, _ = await customer(client, "g3@t.test")
    model.update(tool="draft_complaint", args=ARGS, text="x")         # a model that would happily draft from "no"
    classifier_says("complaints")
    for word in ("no", "yes"):
        out = await turn(u, word)
        assert "nothing waiting" in out["reply"].lower()
    assert await ComplaintDraft.find_all().count() == 0 and await DeliveryIssue.find_all().count() == 0


async def test_a_tracking_number_the_customer_never_gave_is_not_attached_to_the_draft(client, model):
    u, _ = await customer(client, "g4@t.test")
    model.update(tool="draft_complaint", args={**ARGS, "trackingNumber": "SHP12345678"}, text="x")      # invented by the model
    reply = await say(u, "my parcel arrived damaged")
    d = await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])
    assert d is not None and d.trackingNumber is None and "SHP12345678" not in reply


async def test_a_tracking_number_the_customer_did_give_is_kept(client, model):
    from tests.test_tracking_agent_my_shipments import make_shipment
    u, h = await customer(client, "g5@t.test")
    tn = await make_shipment(client, h, "mine")
    model.update(tool="draft_complaint", args={**ARGS, "trackingNumber": tn}, text="x")
    await say(u, f"parcel {tn} arrived damaged")
    assert (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).trackingNumber == tn


@pytest.mark.parametrize("text", ["I want to file a complaint about a damaged parcel", "report a problem with a delivery", "raise an issue please"])
async def test_a_rider_asking_to_file_an_issue_is_answered_before_any_model_runs(client, classifier_says, text):
    classifier_says("tracking")                                       # even when the classifier would send it elsewhere
    out = await turn({"id": "1" * 24, "role": "driver"}, text)
    assert out["source"] == "builtin" and "Operations" in out["reply"] and "not assigned" not in out["reply"]


@pytest.mark.parametrize("who", [None, {"id": "0" * 24, "role": "user"}, {"id": "1" * 24, "role": "driver"}])
async def test_nobody_but_operations_is_offered_the_live_fleet(client, classifier_says, who):
    classifier_says("general")
    out = await turn(who, "Which vehicles are live right now?")
    assert out["source"] == "builtin" and "operations only" in out["reply"].lower()


async def test_a_message_with_a_tracking_number_goes_to_tracking_even_if_misclassified(client, monkeypatch, classifier_says):
    seen = []

    async def spy(message, history, sentiment, current_user=None, on_stage=None):
        seen.append(message)
        return "status"
    monkeypatch.setattr(tracking_agent, "handle", spy)
    classifier_says("complaints")
    out = await turn({"id": "2" * 24, "role": "admin"}, "Where is shipment SHP48217390?")
    assert out["agent"] == "tracking" and seen


async def test_a_complaint_that_mentions_a_tracking_number_still_goes_to_complaints(client, model, classifier_says):
    u, _ = await customer(client, "g6@t.test")
    model.update(tool=None, text="Tell me more.")
    classifier_says("complaints")
    out = await turn(u, "SHP48217390 arrived damaged, I want to complain")
    assert out["agent"] == "complaints"


async def test_when_the_model_only_promises_a_lookup_the_database_answers_instead(client, monkeypatch, classifier_says):
    from agents.base import PROMISE_REPLACEMENT
    from tests.conftest import register
    from tests.test_tracking_agent_my_shipments import make_shipment
    _, ch = await register(client, "user", "g7@t.test")
    tn = await make_shipment(client, ch, "x")

    async def promises(*a, **k):
        return PROMISE_REPLACEMENT
    monkeypatch.setattr(tracking_agent, "handle", promises)
    classifier_says("tracking")
    out = await turn({"id": "2" * 24, "role": "admin"}, f"Where is shipment {tn}?")
    assert tn in out["reply"] and "currently" in out["reply"] and out["source"] == "builtin"
