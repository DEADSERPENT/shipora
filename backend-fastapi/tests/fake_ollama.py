"""A scripted Ollama for tests: an httpx.MockTransport installed on services/ollama_client.py, so the real client code
(request building, tool loop, error handling, cooldown) runs and only the model is fake."""
import json

import httpx

from services import ollama_client

CLASSIFY_GENERAL = '{"agent": "general", "sentiment": "neutral"}'


def install(monkeypatch, handler) -> None:
    monkeypatch.setattr(ollama_client, "_transport", httpx.MockTransport(handler))
    ollama_client.reset()


def failing(monkeypatch, error: Exception) -> dict:
    """Every Ollama call raises `error` (httpx.ConnectError, httpx.ReadTimeout, ...). Returns {"n": calls made}."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise error
    install(monkeypatch, handler)
    return calls


def status(monkeypatch, code: int) -> dict:
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(code, json={"error": "scripted"})
    install(monkeypatch, handler)
    return calls


def says(monkeypatch, text: str) -> dict:
    """The model never calls a tool and always answers `text` (classification gets a general/neutral verdict)."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        body = json.loads(request.content)
        content = CLASSIFY_GENERAL if body.get("format") else text
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})
    install(monkeypatch, handler)
    return calls


def tool_model(monkeypatch, plan: dict, captured: dict, final: str = "final answer") -> None:
    """First (tool-offering) call asks for plan["tool"] with plan["args"]; the tool's JSON result is stored in
    captured["result"] (and its name in captured["name"]); the second call answers `final`. `plan` is read at call time, so a
    test may change it after the fixture ran."""
    def handler(request):
        body = json.loads(request.content)
        if body.get("format"):
            return httpx.Response(200, json={"message": {"role": "assistant", "content": CLASSIFY_GENERAL}})
        tool_msgs = [m for m in body["messages"] if m["role"] == "tool"]
        if tool_msgs:
            captured.update(name=tool_msgs[0].get("tool_name"), result=json.loads(tool_msgs[0]["content"]))
            return httpx.Response(200, json={"message": {"role": "assistant", "content": final}})
        if body.get("tools") and plan.get("tool"):
            call = {"function": {"name": plan["tool"], "arguments": plan.get("args", {})}}
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [call]}})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": final}})
    install(monkeypatch, handler)
