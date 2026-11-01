"""
Refund validation logic for PinHire webhook requests.

The only business rule implemented here is the refund-limit cap.
All coercion and validation is done explicitly so that no customer message,
no matter how cleverly worded, can change the numeric comparison result.
"""

import math
from typing import Any

from app.config import get_settings


class RefundValidationError(Exception):
    """Raised when the refund request fails validation."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def validate_refund_amount(payload: dict[str, Any]) -> float:
    """
    Extract and validate the refund amount from *payload*.

    Validation rules (applied in order):
        1. The ``refund_aed`` field must be present.
        2. The value must be a real number (int or float), not a string,
           list, dict, or boolean masquerading as a number.
        3. The value must be finite (not NaN or Infinity).
        4. The value must be greater than zero (negative amounts rejected).
        5. The value must not exceed MAX_REFUND_AED (520 AED).

    The ``customer_message`` field is completely ignored during limit
    enforcement – it cannot override the numeric check.

    Args:
        payload: Parsed JSON payload dict from the request body.

    Returns:
        The validated refund amount as a float.

    Raises:
        RefundValidationError: If any validation rule is violated.
    """
    settings = get_settings()

    # ── 1. Field presence ─────────────────────────────────────────────────────
    if "refund_aed" not in payload:
        raise RefundValidationError(
            "missing_field",
            "The 'refund_aed' field is required in the payload.",
        )

    raw_amount = payload["refund_aed"]

    # ── 2. Type check – booleans subclass int in Python, reject them ──────────
    if isinstance(raw_amount, bool) or not isinstance(raw_amount, (int, float)):
        raise RefundValidationError(
            "invalid_type",
            "The 'refund_aed' field must be a numeric value.",
        )

    amount = float(raw_amount)

    # ── 3. Finiteness ─────────────────────────────────────────────────────────
    if not math.isfinite(amount):
        raise RefundValidationError(
            "invalid_amount",
            "The 'refund_aed' field must be a finite number.",
        )

    # ── 4. Positive amount ────────────────────────────────────────────────────
    if amount <= 0:
        raise RefundValidationError(
            "invalid_amount",
            "The refund amount must be greater than zero.",
        )

    # ── 5. Limit check ────────────────────────────────────────────────────────
    if amount > settings.MAX_REFUND_AED:
        raise RefundValidationError(
            "refund_limit_exceeded",
            f"Requested refund of {amount} AED exceeds the maximum of "
            f"{settings.MAX_REFUND_AED} AED.",
        )

    return amount
