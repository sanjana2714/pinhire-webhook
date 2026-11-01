"""
FAQ handling for PinHire webhook requests.

Design:
    - Responses are stored in a static dict keyed by normalised question text.
    - Normalisation: strip leading/trailing whitespace, collapse internal
      whitespace, and lower-case the entire string.
    - A simple dict lookup acts as a cache since the mapping is immutable.
    - No external API calls are made, ensuring sub-650 ms response times.
    - The FAQ payload is parsed in an isolated function so the schema can
      be adjusted without touching the main endpoint.

To add or modify questions, edit the FAQS dict below.
"""

import re
from typing import Any


# ── Predefined FAQ responses ──────────────────────────────────────────────────
# Keys are already normalised (lowercase, collapsed whitespace).
FAQS: dict[str, str] = {
    "what is pinhire": (
        "PinHire is a workforce management and payment platform that connects "
        "businesses with skilled professionals and streamlines payment workflows."
    ),
    "how do i request a refund": (
        "To request a refund, submit a POST request to /api/guard with event "
        "'refund.requested' and a signed payload containing your tx_ref_9268 "
        "and refund_aed amount. Refunds up to 520 AED are processed automatically."
    ),
    "what is the maximum refund amount": (
        "The maximum permitted refund is 520 AED per transaction."
    ),
    "how long does a refund take": (
        "Refund requests are validated instantly. Actual settlement time depends "
        "on your payment provider, typically 3–5 business days."
    ),
    "how is the hmac signature calculated": (
        "Compute HMAC-SHA256 over the raw JSON request body using your seed token "
        "as the key. Encode the digest as a lowercase hex string and send it in "
        "the x-pinhire-hmac-9268 header."
    ),
    "what happens if i send the same transaction twice": (
        "Duplicate transactions (same tx_ref_9268 within 90 seconds) are detected "
        "and rejected with a 'duplicate' status. Only the first request is processed."
    ),
    "how do i contact support": (
        "Please email support@pinhire.com or open a ticket via your dashboard."
    ),
    "what currencies are supported": (
        "Currently only AED (UAE Dirham) is supported for refund transactions."
    ),
    "is my data secure": (
        "Yes. All webhook requests are authenticated via HMAC-SHA256 signatures. "
        "No sensitive data is logged or exposed through API responses."
    ),
    "what is the idempotency window": (
        "Each transaction reference (tx_ref_9268) is locked for 90 seconds. "
        "Duplicate requests within this window are automatically rejected."
    ),
}


def _normalise(text: str) -> str:
    """
    Normalise a question string for lookup.

    Steps:
        1. Strip leading/trailing whitespace.
        2. Collapse internal runs of whitespace to a single space.
        3. Convert to lowercase.
    """
    return re.sub(r"\s+", " ", text.strip()).lower()


def parse_faq_payload(payload: dict[str, Any]) -> str:
    """
    Extract the question from a FAQ event payload.

    Expected payload shape::

        {"question": "How do I request a refund?"}

    Raises:
        ValueError: If the 'question' field is missing or not a string.
    """
    question = payload.get("question")
    if question is None:
        raise ValueError("The FAQ payload must contain a 'question' field.")
    if not isinstance(question, str):
        raise ValueError("The 'question' field must be a string.")
    return question


def answer_faq(raw_question: str) -> dict[str, str]:
    """
    Return a FAQ response dict for *raw_question*.

    The lookup is performed after normalising the question so that minor
    variations in casing or whitespace are handled transparently.

    Args:
        raw_question: The question string from the request payload.

    Returns:
        A dict with ``status`` and ``answer`` keys.  If no matching FAQ
        is found ``status`` is still ``"answered"`` but the answer
        indicates that the question is not recognised.
    """
    normalised = _normalise(raw_question)
    answer = FAQS.get(normalised)

    if answer is None:
        return {
            "status": "answered",
            "answer": (
                "Sorry, I don't have an answer for that question. "
                "Please contact support@pinhire.com for assistance."
            ),
        }

    return {"status": "answered", "answer": answer}
