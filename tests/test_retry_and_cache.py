import asyncio
import random

import pytest

from app.cache import InMemoryCache
from app.retry import RetryPolicy, with_retry
from app.sources.base import SourceError, TransientSourceError


async def _no_sleep(_):
    return None


def test_retries_transient_errors_then_succeeds():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TransientSourceError("503")
        return "ok"

    result = asyncio.run(with_retry(flaky, RetryPolicy(max_attempts=3), sleep=_no_sleep))
    assert result == "ok"
    assert len(calls) == 3


def test_gives_up_after_max_attempts():
    calls = []

    async def always_down():
        calls.append(1)
        raise TransientSourceError("timeout")

    with pytest.raises(TransientSourceError):
        asyncio.run(with_retry(always_down, RetryPolicy(max_attempts=2), sleep=_no_sleep))
    assert len(calls) == 2


def test_permanent_errors_are_not_retried():
    calls = []

    async def bad_request():
        calls.append(1)
        raise SourceError("400")

    with pytest.raises(SourceError):
        asyncio.run(with_retry(bad_request, RetryPolicy(max_attempts=5), sleep=_no_sleep))
    assert len(calls) == 1


def test_slow_calls_time_out_and_are_retried():
    calls = []

    async def slow():
        calls.append(1)
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        asyncio.run(
            with_retry(slow, RetryPolicy(max_attempts=2, timeout=0.01), sleep=_no_sleep)
        )
    assert len(calls) == 2


def test_backoff_is_capped_and_jittered():
    policy = RetryPolicy(base_delay=1, max_delay=4)
    rng = random.Random(7)
    delays = [policy.delay_for(attempt, rng) for attempt in range(10)]
    assert all(0 <= d <= 4 for d in delays)
    assert len(set(delays)) > 1


def test_in_memory_cache_expires_entries():
    now = [0.0]
    cache = InMemoryCache(clock=lambda: now[0])
    asyncio.run(cache.set("k", {"a": 1}, ttl_seconds=10))
    assert asyncio.run(cache.get("k")) == {"a": 1}
    now[0] = 11
    assert asyncio.run(cache.get("k")) is None
