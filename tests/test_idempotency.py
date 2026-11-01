"""
Tests for idempotency (app/idempotency.py and POST /api/guard).

Covers:
    - A repeated transaction reference within the TTL.
    - Two simultaneous requests with the same tx_ref.
    - Idempotency expiration after the TTL (90 seconds simulated via monkeypatch).
    - Missing tx_ref field.
    - Requests arriving with the same valid body and signature.
"""

import asyncio
import hashlib
import hmac
import json
import os
import time

import pytest

os.environ.setdefault("PINHIRE_SEED_TOKEN", "SEED-9268-PH-1A1E")

from fastapi.testclient import TestClient  # noqa: E402

import app.idempotency as idempotency_module  # noqa: E402
from app.idempotency import check_and_record, clear_store  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
TEST_KEY = "SEED-9268-PH-1A1E"
HEADER = "x-pinhire-hmac-9268"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_refund_request(tx_ref: str, amount: float = 100) -> tuple[bytes, str]:
    body = json.dumps(
        {
            "event": "refund.requested",
            "payload": {"tx_ref_9268": tx_ref, "refund_aed": amount},
        },
        separators=(",", ":"),
    ).encode()
    sig = hmac.new(TEST_KEY.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def _post_refund(tx_ref: str, amount: float = 100):
    raw, sig = _make_refund_request(tx_ref, amount)
    return client.post("/api/guard", content=raw, headers={HEADER: sig})


def _run(coro):
    """Run a coroutine in the current event loop or a new one."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_idempotency_store():
    """Clear the idempotency store before each test."""
    _run(clear_store())
    yield
    _run(clear_store())


# ── Unit tests for idempotency module ────────────────────────────────────────

class TestCheckAndRecord:
    def test_first_call_returns_false(self):
        result = _run(check_and_record("TXN-IDEM-UNIT-001"))
        assert result is False  # not a duplicate

    def test_second_call_returns_true(self):
        _run(check_and_record("TXN-IDEM-UNIT-002"))
        result = _run(check_and_record("TXN-IDEM-UNIT-002"))
        assert result is True  # duplicate

    def test_different_refs_not_duplicate(self):
        _run(check_and_record("TXN-IDEM-A"))
        result = _run(check_and_record("TXN-IDEM-B"))
        assert result is False

    def test_expired_record_allows_reprocessing(self, monkeypatch):
        """
        Simulate TTL expiry by back-dating the first_seen timestamp so the
        record appears older than 90 seconds.
        """
        tx_ref = "TXN-IDEM-EXPIRE-001"

        # Record the transaction.
        _run(check_and_record(tx_ref))

        # Manually back-date the stored timestamp to simulate expiry.
        idempotency_module._store[tx_ref]["first_seen"] -= 91  # > 90 s ago

        # Now the same ref should be treated as new.
        result = _run(check_and_record(tx_ref))
        assert result is False  # not a duplicate – record was expired


# ── Integration tests via HTTP ────────────────────────────────────────────────

class TestIdempotencyEndpoint:
    def test_first_request_processed(self):
        resp = _post_refund("TXN-IDEM-HTTP-001")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processed"

    def test_repeated_request_returns_duplicate(self):
        _post_refund("TXN-IDEM-HTTP-002")  # first
        resp = _post_refund("TXN-IDEM-HTTP-002")  # duplicate
        assert resp.status_code == 200
        assert resp.json()["status"] == "duplicate"

    def test_same_body_and_signature_detected_as_duplicate(self):
        """
        The same raw body (and thus the same valid signature) sent twice
        must result in a duplicate on the second call.
        """
        raw, sig = _make_refund_request("TXN-IDEM-SAME-BODY-001")
        r1 = client.post("/api/guard", content=raw, headers={HEADER: sig})
        r2 = client.post("/api/guard", content=raw, headers={HEADER: sig})
        assert r1.json()["status"] == "processed"
        assert r2.json()["status"] == "duplicate"

    def test_missing_tx_ref_returns_400(self):
        body = json.dumps(
            {"event": "refund.requested", "payload": {"refund_aed": 100}},
            separators=(",", ":"),
        ).encode()
        sig = hmac.new(TEST_KEY.encode(), body, hashlib.sha256).hexdigest()
        resp = client.post("/api/guard", content=body, headers={HEADER: sig})
        assert resp.status_code == 400
        assert resp.json()["reason"] == "missing_tx_ref"

    def test_concurrent_same_tx_ref_only_one_processed(self):
        """
        Fire two concurrent requests with the same tx_ref.  Exactly one
        must be processed; the other must be duplicate.
        """
        tx_ref = "TXN-IDEM-CONCURRENT-001"
        raw, sig = _make_refund_request(tx_ref)

        results = []

        async def _send():
            import httpx
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                tasks = [
                    ac.post(
                        "/api/guard",
                        content=raw,
                        headers={HEADER: sig, "content-type": "application/json"},
                    )
                    for _ in range(2)
                ]
                responses = await asyncio.gather(*tasks)
                results.extend(responses)

        asyncio.run(_send())
        statuses = [r.json()["status"] for r in results]
        assert statuses.count("processed") == 1
        assert statuses.count("duplicate") == 1

    def test_idempotency_expires_after_ttl(self, monkeypatch):
        """
        After the TTL expires the same tx_ref should be processable again.
        """
        tx_ref = "TXN-IDEM-TTL-EXP-001"
        _post_refund(tx_ref)  # first – processed

        # Back-date the stored timestamp to simulate expiry.
        # The TestClient uses its own event loop; _store is module-level so
        # direct dict access is safe here.
        idempotency_module._store[tx_ref]["first_seen"] -= 91

        resp = _post_refund(tx_ref)  # should be treated as new
        assert resp.json()["status"] == "processed"
