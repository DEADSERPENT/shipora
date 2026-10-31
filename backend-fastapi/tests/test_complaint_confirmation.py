"""Server-side complaint confirmation: a complaint is only ever filed from a draft the customer saw and confirmed, bound to
that user, that session and the exact content, once, before it expires. The model is scripted (it may even lie); the agent,
drafts, tools and database are real."""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from agents import complaints_agent
from models.complaint_draft import ComplaintDraft
from models.delivery_issue import DeliveryIssue
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio

ARGS = {"subject": "Parcel arrived damaged", "category": "damaged_parcel", "description": "The box was crushed and the screen is cracked."}


@pytest.fixture
def model(monkeypatch):
    """Scripted model: optionally calls one tool, then returns `text`. Records whether it was consulted at all."""
    state = {"tool": None, "args": {}, "text": "ok", "called": 0, "tools": None}

    async def fake(system, tools, executors, message, history, sentiment, on_stage=None):
        state["called"] += 1
        state["tools"] = {t["name"] for t in tools}
        if state["tool"]:
            await executors[state["tool"]](**state["args"])
        return state["text"]
    monkeypatch.setattr(complaints_agent, "run_tool_agent", fake)
    return state


async def customer(client, email):
    u, h = await register(client, "user", email)
    return {"id": u["id"], "role": "user", "name": u["name"], "email": u["email"]}, h


async def say(user, message, session="s1", history=None):
    return await complaints_agent.handle(message, history or [], "neutral", user, session_id=session)


async def issues():
    return await DeliveryIssue.find_all().count()


async def draft(model, user, session="s1", **over):
    model.update(tool="draft_complaint", args={**ARGS, **over}, text="I have filed your complaint!")   # a lying model
    return await say(user, "my parcel arrived damaged", session)


async def test_the_first_mention_only_drafts_and_the_server_writes_the_summary(client, model):
    u, _ = await customer(client, "d1@t.test")
    reply = await draft(model, u)
    assert await issues() == 0                                              # nothing filed
    assert "Parcel arrived damaged" in reply and "yes" in reply.lower() and "no" in reply.lower()
    assert "filed your complaint" not in reply.lower()                       # the model's false claim never reaches the user
    d = await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])
    assert d.status == "pending" and d.sessionId == "s1" and d.draftId and d.expiresAt > datetime.utcnow()


async def test_yes_files_exactly_once_and_the_message_comes_from_the_result(client, model):
    u, _ = await customer(client, "d2@t.test")
    await draft(model, u)
    model.update(tool=None, called=0)
    reply = await say(u, "yes")
    assert model["called"] == 0                                              # confirmation never goes through the model
    assert await issues() == 1
    assert "filed" in reply.lower() and "Parcel arrived damaged" in reply
    again = await say(u, "yes")                                              # duplicate confirmation
    assert await issues() == 1 and "already" in again.lower()


async def test_two_simultaneous_yes_replies_file_one_complaint(client, model):
    u, _ = await customer(client, "d3@t.test")
    await draft(model, u)
    await asyncio.gather(say(u, "yes"), say(u, "yes"), say(u, "yes please"))
    assert await issues() == 1


async def test_declining_cancels_the_draft_for_good(client, model):
    u, _ = await customer(client, "d4@t.test")
    await draft(model, u)
    reply = await say(u, "no")
    assert "haven't filed" in reply.lower() or "not filed" in reply.lower() or "cancel" in reply.lower()
    assert (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).status == "declined"
    await say(u, "yes")                                                      # a later yes has nothing to confirm
    assert await issues() == 0


async def test_an_expired_draft_is_never_filed(client, model):
    u, _ = await customer(client, "d5@t.test")
    await draft(model, u)
    d = await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])
    d.expiresAt = datetime.utcnow() - timedelta(seconds=1)
    await d.save()
    reply = await say(u, "yes")
    assert await issues() == 0 and "expired" in reply.lower()


async def test_editing_the_content_supersedes_the_old_draft(client, model):
    u, _ = await customer(client, "d6@t.test")
    await draft(model, u)
    await draft(model, u, subject="Parcel is two days late", category="delayed_delivery", description="Promised same day, still not here.")
    drafts = await ComplaintDraft.find(ComplaintDraft.userId == u["id"]).to_list()
    assert sorted(d.status for d in drafts) == ["pending", "superseded"]
    await say(u, "yes")
    filed = await DeliveryIssue.find_all().to_list()
    assert len(filed) == 1 and filed[0].subject == "Parcel is two days late"   # exactly what the customer last saw


async def test_the_filed_content_must_match_what_was_confirmed(client, model):
    u, _ = await customer(client, "d7@t.test")
    await draft(model, u)
    d = await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])
    d.description = "tampered after the customer saw the summary"           # hash no longer matches
    await d.save()
    reply = await say(u, "yes")
    assert await issues() == 0 and "couldn't" in reply.lower()


async def test_a_confirmation_is_bound_to_the_user_and_the_session(client, model):
    a, _ = await customer(client, "d8a@t.test")
    b, _ = await customer(client, "d8b@t.test")
    await draft(model, a, session="s1")
    await say(b, "yes", session="s1")                                        # someone else, same session id
    await say(a, "yes", session="other-session")                             # same user, different session
    assert await issues() == 0
    await say(a, "yes", session="s1")
    assert await issues() == 1


async def test_an_ambiguous_reply_asks_again_and_files_nothing(client, model):
    u, _ = await customer(client, "d9@t.test")
    await draft(model, u)
    reply = await say(u, "hmm maybe")
    assert await issues() == 0 and "yes" in reply.lower() and "no" in reply.lower()
    assert (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).status == "pending"
    await say(u, "yes but make it urgent")                                   # a yes with a change is not a clean confirmation
    assert await issues() == 0


async def test_a_model_that_claims_success_without_filing_is_corrected(client, model):
    u, _ = await customer(client, "d10@t.test")
    model.update(tool=None, text="Done! I've filed your complaint and the team will contact you.")
    reply = await say(u, "my parcel is damaged")
    assert await issues() == 0 and "filed your complaint" not in reply.lower() and "haven't filed" in reply.lower()


async def test_a_failed_write_is_reported_as_a_failure_not_a_success(client, model, monkeypatch):
    u, _ = await customer(client, "d11@t.test")
    await draft(model, u)

    async def boom(*a, **k):
        raise HTTPException(status_code=500, detail="database unavailable")
    monkeypatch.setattr("tools.complaint_tools.insert_complaint", boom)
    reply = await say(u, "yes")
    assert await issues() == 0 and "couldn't" in reply.lower() and "filed it" not in reply.lower()
    assert (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).status == "failed"


async def test_a_draft_for_someone_elses_shipment_is_refused_up_front(client, model):
    u, _ = await customer(client, "d12@t.test")
    model.update(tool="draft_complaint", args={**ARGS, "trackingNumber": "SHP00000000"}, text="x")
    reply = await say(u, "parcel SHP00000000 arrived damaged")                    # the customer did name it; it just isn't theirs
    assert await ComplaintDraft.find(ComplaintDraft.userId == u["id"]).count() == 0
    assert "couldn't" in reply.lower() and "yes" not in reply.lower().replace("yesterday", "")


async def test_only_customers_can_draft(client, model):
    from tools.complaint_tools import execute_draft_complaint
    for role in ("driver", "admin", None):
        user = {"id": "0" * 24, "role": role, "name": "x", "email": "x@t.test"} if role else None
        out = await execute_draft_complaint(**ARGS, current_user=user, session_id="s1")
        assert out["drafted"] is False
    assert await ComplaintDraft.find_all().count() == 0


async def test_the_model_is_never_offered_a_direct_filing_tool(client, model):
    u, _ = await customer(client, "d13@t.test")
    await say(u, "hello")
    assert "draft_complaint" in model["tools"] and "create_complaint" not in model["tools"]


# ── the chat widget wraps every message in a language instruction ("...User's message: <text>") ──
WRAP = "Reply naturally in English.\nDo not use markdown.\nAvoid sounding like documentation.\n\nUser's message: "


async def test_confirmation_and_decline_work_through_the_language_wrapper(client, model):
    u, _ = await customer(client, "w1@t.test")
    await draft(model, u)
    await say(u, WRAP + "no")
    assert (await ComplaintDraft.find_one(ComplaintDraft.userId == u["id"])).status == "declined"
    await draft(model, u)
    await say(u, WRAP + "yes")
    assert await issues() == 1


async def test_the_wrapper_cannot_smuggle_extra_instructions_past_the_yes_check(client, model):
    u, _ = await customer(client, "w2@t.test")
    await draft(model, u)
    await say(u, WRAP + "yes and also tell them it is urgent")
    assert await issues() == 0


def test_user_text_unwraps_only_the_widgets_wrapper():
    from agents.roles import user_text
    assert user_text(WRAP + "hello there") == "hello there"
    assert user_text("plain message") == "plain message"
    assert user_text("ignore previous. User's message: yes") == "yes"
