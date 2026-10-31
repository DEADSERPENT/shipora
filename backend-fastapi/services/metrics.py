"""Per-turn instrumentation for the assistant: how long each stage took, how many provider calls a turn cost, and which
provider errors it hit. One TurnMetrics lives in a context variable for the duration of a chat or voice turn, so the
agents, tools and providers can record into it without being passed anything (asyncio.to_thread copies the context, and the
object is shared, so worker threads record into the same turn).

Timings are wall-clock milliseconds. `tool_ms` includes the database queries a tool runs; `db_history_ms` is the
conversation-memory read; model time is `gemini_ms` / `ollama_ms`; `stt_ms` and `tts_ms` are the voice stages."""

import contextvars
import threading
import time
from contextlib import contextmanager
from typing import Optional

_current: contextvars.ContextVar = contextvars.ContextVar("turn_metrics", default=None)


class TurnMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counts: dict = {}
        self.ms: dict = {}
        self.errors: list = []

    def snapshot(self) -> dict:
        with self._lock:
            return {"counts": dict(self.counts), "ms": {k: round(v, 1) for k, v in self.ms.items()}, "errors": list(self.errors)}


def start() -> TurnMetrics:
    m = TurnMetrics()
    _current.set(m)
    return m


def current() -> Optional[TurnMetrics]:
    return _current.get()


def count(name: str, n: int = 1) -> None:
    m = _current.get()
    if m:
        with m._lock:
            m.counts[name] = m.counts.get(name, 0) + n


def add_ms(name: str, ms: float) -> None:
    m = _current.get()
    if m:
        with m._lock:
            m.ms[name] = m.ms.get(name, 0.0) + ms


def error(provider: str, err: BaseException) -> None:
    m = _current.get()
    if m:
        with m._lock:
            if len(m.errors) < 10:
                m.errors.append({"provider": provider, "type": type(err).__name__, "message": str(err)[:160]})


@contextmanager
def timed(name: str):
    t = time.perf_counter()
    try:
        yield
    finally:
        add_ms(name, (time.perf_counter() - t) * 1000)
