"""Opt-in request-local read deadline; no state survives the enclosing operation."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

_deadline: ContextVar[float | None] = ContextVar("bounded_read_deadline", default=None)


class ReadBudgetExceeded(TimeoutError):
    """Only the caller can decide whether a completed read prefix is useful."""


def remaining_ms() -> int | None:
    deadline = _deadline.get()
    if deadline is None:
        return None
    remaining = int((deadline - monotonic()) * 1000)
    if remaining <= 0:
        raise ReadBudgetExceeded("Read deadline exceeded")
    return min(remaining, 3000)


@contextmanager
def bounded_read(seconds: float = 12):
    prior = _deadline.get()
    token = _deadline.set(min(prior, monotonic() + seconds) if prior else monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)
