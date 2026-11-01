"""
HMAC-SHA256 signature verification for PinHire webhook requests.

The signing process is:
    digest = HMAC-SHA256(key=seed_token, message=raw_request_body)
    hex_digest = digest.hexdigest()   # lowercase hex

The caller must supply the *raw* request bytes before any JSON parsing so
that whitespace differences never cause a false verification failure.
"""

import hashlib
import hmac

from app.config import get_settings


def compute_hmac(raw_body: bytes) -> str:
    """
    Compute the expected HMAC-SHA256 hex digest for *raw_body*.

    Args:
        raw_body: The exact bytes received in the HTTP request body.

    Returns:
        Lowercase hexadecimal HMAC-SHA256 digest string.
    """
    settings = get_settings()
    key = settings.seed_token.encode("utf-8")
    digest = hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    return digest


def verify_signature(raw_body: bytes, supplied_signature: str | None) -> bool:
    """
    Verify that *supplied_signature* matches the HMAC of *raw_body*.

    Uses ``hmac.compare_digest`` for constant-time comparison to prevent
    timing side-channel attacks.

    Args:
        raw_body:           Raw HTTP request body bytes.
        supplied_signature: Value of the ``x-pinhire-hmac-9268`` header, or
                            ``None`` if the header was absent.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    if not supplied_signature:
        # Missing header – reject immediately.
        return False

    expected = compute_hmac(raw_body)

    # Both strings must be the same type for compare_digest.
    try:
        return hmac.compare_digest(expected, supplied_signature.lower().strip())
    except (TypeError, ValueError):
        return False
