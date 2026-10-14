"""Async retry with exponential backoff and full jitter, for transient errors only."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.sources.base import TransientSourceError


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 5.0
    timeout: float = 10.0

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """Full jitter: uniform(0, min(max_delay, base * 2**attempt))."""
        cap = min(self.max_delay, self.base_delay * (2**attempt))
        return (rng or random).uniform(0, cap)


async def with_retry[T](
    call: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run `call` with a per-attempt timeout; retry timeouts and TransientSourceError.

    Permanent errors (anything else) propagate immediately.
    """
    last_error: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return await asyncio.wait_for(call(), timeout=policy.timeout)
        except (TransientSourceError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < policy.max_attempts:
                await sleep(policy.delay_for(attempt))
    assert last_error is not None
    raise last_error
