"""
Configuration module for the PinHire Webhook application.

All task-specific constants and environment-driven settings are centralised
here so the rest of the codebase never hard-codes secrets or magic numbers.
"""

import os
from functools import lru_cache


class Settings:
    """
    Application settings.

    The signing key is read from the PINHIRE_SEED_TOKEN environment variable
    at startup.  In local development you can export the variable in your
    shell or place it in a .env file (loaded by a tool such as python-dotenv
    or direnv – NOT committed to Git).

    Example (Linux / macOS):
        export PINHIRE_SEED_TOKEN="SEED-9268-PH-1A1E"

    Example (Windows PowerShell):
        $env:PINHIRE_SEED_TOKEN = "SEED-9268-PH-1A1E"

    WARNING: Never hard-code the real token in source files that are
    committed to version control.
    """

    # ── Task-specific constants (not secrets) ────────────────────────────────
    SIGNATURE_HEADER: str = "x-pinhire-hmac-9268"
    TX_REF_FIELD: str = "tx_ref_9268"
    MAX_REFUND_AED: float = 520.0
    IDEMPOTENCY_TTL_SECONDS: int = 90
    FAQ_RESPONSE_TARGET_MS: int = 650

    # ── Supported event types ─────────────────────────────────────────────────
    EVENT_REFUND: str = "refund.requested"
    EVENT_FAQ: str = "faq.query"

    # ── Secret – loaded from environment ─────────────────────────────────────
    @property
    def seed_token(self) -> str:
        """
        Return the HMAC signing key.

        Raises RuntimeError if the environment variable is not set so the
        application fails fast rather than silently using an empty key.
        """
        token = os.environ.get("PINHIRE_SEED_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "PINHIRE_SEED_TOKEN environment variable is not set. "
                "Set it before starting the application."
            )
        return token

    # ── Server settings ───────────────────────────────────────────────────────
    @property
    def port(self) -> int:
        """Port is read from Railway's PORT env var, defaulting to 8000."""
        return int(os.environ.get("PORT", "8000"))

    host: str = "0.0.0.0"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
