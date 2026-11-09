"""Webhook signatures.

What is signed, exactly:

    key     = the endpoint's signing secret, the whole text including "whsec_", as UTF-8 bytes
    message = the timestamp as decimal digits, then a dot, then the request body bytes exactly as sent
              (for example   b"1793354400." + b'{"id":"..."}'   )
    result  = "sha256=" + lowercase hex of HMAC-SHA256(key, message)

The same timestamp is sent in the X-HookFlow-Timestamp header (Unix seconds). A receiver should recompute the
signature from the RAW body bytes (before any JSON parsing), compare it in constant time, and reject requests
whose timestamp is more than 5 minutes away from its own clock, so a captured request cannot be replayed later.
"""

import hashlib
import hmac
import time

DEFAULT_TOLERANCE_SECONDS = 300


def sign_payload(secret: str, timestamp: int, raw_body: bytes) -> str:
    message = str(timestamp).encode("ascii") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str,
    timestamp_header: str,
    signature_header: str,
    raw_body: bytes,
    *,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> bool:
    """What a receiver does. Included so our tests, and anyone reading, use the same rule."""
    try:
        timestamp = int(timestamp_header)
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - timestamp) > tolerance_seconds:
        return False
    expected = sign_payload(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature_header or "")