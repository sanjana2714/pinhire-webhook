"""
Tests for HMAC signature verification (app/security.py).

Each test generates its own correct or incorrect signature so that
no hard-coded strings need to change when the test key changes.
"""

import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

# Set env var BEFORE importing the app so Settings.seed_token works.
TEST_KEY = "SEED-9268-PH-1A1E"
os.environ.setdefault("PINHIRE_SEED_TOKEN", TEST_KEY)

from app.main import app  # noqa: E402
from app.security import compute_hmac, verify_signature  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

HEADER = "x-pinhire-hmac-9268"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_body(**payload_fields) -> bytes:
    """Build a minimal valid refund request body as raw bytes."""
    body = {
        "event": "refund.requested",
        "payload": {
            "tx_ref_9268": payload_fields.get("tx_ref", "TXN-SEC-001"),
            "refund_aed": payload_fields.get("refund_aed", 100),
        },
    }
    return json.dumps(body, separators=(",", ":")).encode()


def _sign(raw: bytes) -> str:
    return hmac.new(TEST_KEY.encode(), raw, hashlib.sha256).hexdigest()


# ── Unit tests for security helpers ──────────────────────────────────────────

class TestComputeHmac:
    def test_returns_lowercase_hex(self):
        raw = b'{"event":"test"}'
        digest = compute_hmac(raw)
        assert digest == digest.lower()
        assert all(c in "0123456789abcdef" for c in digest)

    def test_length_is_64_chars(self):
        digest = compute_hmac(b"hello")
        assert len(digest) == 64

    def test_different_bodies_produce_different_digests(self):
        assert compute_hmac(b"body1") != compute_hmac(b"body2")

    def test_same_body_is_deterministic(self):
        raw = b'{"deterministic":true}'
        assert compute_hmac(raw) == compute_hmac(raw)


class TestVerifySignature:
    def test_valid_signature_accepted(self):
        raw = b'{"valid":true}'
        sig = _sign(raw)
        assert verify_signature(raw, sig) is True

    def test_invalid_signature_rejected(self):
        raw = b'{"valid":true}'
        assert verify_signature(raw, "deadbeef" * 8) is False

    def test_none_signature_rejected(self):
        assert verify_signature(b"body", None) is False

    def test_empty_string_signature_rejected(self):
        assert verify_signature(b"body", "") is False

    def test_uppercase_signature_accepted(self):
        raw = b'{"case":"upper"}'
        sig = _sign(raw).upper()
        assert verify_signature(raw, sig) is True


# ── Integration tests via HTTP ────────────────────────────────────────────────

class TestSignatureEndpoint:
    def test_valid_signature_returns_200(self):
        raw = _make_body(tx_ref="TXN-SIG-VALID-001")
        sig = _sign(raw)
        resp = client.post("/api/guard", content=raw, headers={HEADER: sig})
        assert resp.status_code == 200

    def test_invalid_signature_returns_401(self):
        raw = _make_body(tx_ref="TXN-SIG-INVALID-001")
        resp = client.post(
            "/api/guard", content=raw, headers={HEADER: "wrong" * 10}
        )
        assert resp.status_code == 401
        assert resp.json()["reason"] == "invalid_signature"

    def test_missing_signature_header_returns_401(self):
        raw = _make_body(tx_ref="TXN-SIG-MISSING-001")
        resp = client.post("/api/guard", content=raw)
        assert resp.status_code == 401
        assert resp.json()["reason"] == "invalid_signature"

    def test_tampered_body_returns_401(self):
        """Changing the body after signing must invalidate the signature."""
        original = _make_body(tx_ref="TXN-SIG-TAMPER-001")
        sig = _sign(original)
        tampered = original.replace(b"100", b"9999")
        resp = client.post("/api/guard", content=tampered, headers={HEADER: sig})
        assert resp.status_code == 401
