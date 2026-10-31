"""Guard rails shared by every Gemini call (classification, tool-calling agents, plain-text fallback).

Why this exists: google-generativeai retries transient failures for up to 600 s by default, and a per-call
`timeout` alone does not shorten that. A DNS/network failure therefore froze a voice request for ~29 minutes
(three chained calls x the retry window). Two things fix it:

  * request_options(): every call gets a hard time budget (GEMINI_TIMEOUT_SECONDS, default 20 s) with a small
    retry *inside* that budget, so a blip is retried but an outage fails in about the budget.
  * a cooldown: after an availability failure (timeout, no network, 5xx, quota) further Gemini calls are skipped for
    GEMINI_COOLDOWN_SECONDS and callers use their existing fallbacks immediately, instead of every remaining call
    in the turn waiting out its own budget. A successful call clears it.

Errors that are about one request (a 400, a bad tool argument) do not trip the cooldown.
"""

import contextvars
import logging
import threading
import time

import config
from services import metrics

log = logging.getLogger("shipora.gemini")

_lock = threading.Lock()
_down_until = 0.0  # time.monotonic() deadline; 0 = healthy
# A caller on the phone will not wait 20 s. voice/pipeline.py sets a tighter per-turn budget here; asyncio.to_thread
# copies the context, so agent worker threads see it. None = use GEMINI_TIMEOUT_SECONDS.
budget_override: contextvars.ContextVar = contextvars.ContextVar("gemini_budget", default=None)


def request_options() -> dict:
    """Per-call options for generate_content()/send_message(): hard budget, retries only within it."""
    from google.api_core import retry as gretry

    metrics.count("gemini_calls")        # every Gemini call (classify, tool decision, final text, plain text) builds exactly one of these
    budget = float(budget_override.get() or config.GEMINI_TIMEOUT_SECONDS)
    return {"timeout": budget, "retry": gretry.Retry(initial=0.5, maximum=2.0, multiplier=2.0, timeout=budget)}


def is_unavailable() -> bool:
    return time.monotonic() < _down_until


def is_availability_error(err: BaseException) -> bool:
    from google.api_core import exceptions as gexc

    return isinstance(err, (
        gexc.RetryError, gexc.DeadlineExceeded, gexc.ServiceUnavailable, gexc.GatewayTimeout,
        gexc.InternalServerError, gexc.TooManyRequests, TimeoutError, ConnectionError,
    ))


def note_failure(err: BaseException) -> None:
    """Call from an `except` around a Gemini call. Opens the cooldown only for availability errors."""
    global _down_until
    metrics.error("gemini", err)
    from google.api_core import exceptions as gexc
    if isinstance(err, gexc.TooManyRequests):
        metrics.count("gemini_rate_limited")
    if not is_availability_error(err):
        return
    with _lock:
        already = time.monotonic() < _down_until
        _down_until = time.monotonic() + float(config.GEMINI_COOLDOWN_SECONDS)
    if not already:
        log.warning("Gemini unavailable; using fallbacks", extra={"event": "gemini_unavailable", "error_type": type(err).__name__, "cooldown_seconds": config.GEMINI_COOLDOWN_SECONDS})


def note_success() -> None:
    global _down_until
    _down_until = 0.0


def reset() -> None:
    note_success()
