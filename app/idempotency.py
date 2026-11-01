"""
Concurrency-safe in-memory idempotency store for PinHire webhook requests.

Design:
    - Uses a dict keyed by transaction reference (tx_ref).
    - Each entry records the Unix timestamp when the tx was first seen.
    - An asyncio.Lock ensures the check-and-record step is atomic within a
      single process, preventing race conditions when concurrent requests
      carry the same tx_ref.
    - Records are lazily expired: any access sweeps stale entries first so
      memory does not grow unboundedly.

LIMITATIONS (single-process in-memory):
    - State is lost on process restart.
    - Does NOT work across multiple worker processes or instances.
    - For multi-worker / multi-instance deployments use Redis with an atomic
      SET NX PX operation (see README for details).
"""

import asyncio
import time
from typing import TypedDict

from app.config import get_settings


class _IdempotencyRecord(TypedDict):
    first_seen: float   # Unix epoch seconds


# Module-level lock and store – shared across all requests in the process.
_lock: asyncio.Lock = asyncio.Lock()
_store: dict[str, _IdempotencyRecord] = {}


def _expire_stale_records(ttl: int) -> None:
    """
    Remove records older than *ttl* seconds.

    Must be called while holding ``_lock`` to avoid concurrent modification.
    """
    now = time.monotonic()
    stale = [ref for ref, rec in _store.items() if now - rec["first_seen"] > ttl]
    for ref in stale:
        del _store[ref]


async def check_and_record(tx_ref: str) -> bool:
    """
    Atomically check whether *tx_ref* is a duplicate and, if not, record it.

    Args:
        tx_ref: The transaction reference extracted from the request payload.

    Returns:
        ``True``  – this is a **duplicate** (tx was already seen within TTL).
        ``False`` – this is a **new** transaction (it has now been recorded).
    """
    settings = get_settings()
    ttl = settings.IDEMPOTENCY_TTL_SECONDS

    async with _lock:
        _expire_stale_records(ttl)

        if tx_ref in _store:
            return True  # duplicate

        # Record the new transaction.
        _store[tx_ref] = {"first_seen": time.monotonic()}
        return False


async def clear_store() -> None:
    """
    Reset the idempotency store.

    Intended for use in tests only – do not call in production code.
    """
    async with _lock:
        _store.clear()
