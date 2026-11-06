"""Project API keys look like:  hf_live_<8 hex>_<48 hex>

- `hf_live_<8 hex>` is the public prefix. It is stored in clear so you can recognise a key in a list.
- The 48 hex characters are the secret (192 random bits). Only a SHA-256 hash of the whole key is stored,
  so a database leak does not reveal usable keys. A fast hash is fine here because the key is long and random
  (unlike a human password, it cannot be guessed).
"""

import hashlib
import hmac
import re
import secrets

KEY_PREFIX = "hf_live_"
_KEY_PATTERN = re.compile(r"^hf_live_([0-9a-f]{8})_[0-9a-f]{48}$")


def generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, public_prefix, secret_hash). The raw key is shown to the user once, then forgotten."""
    identifier = secrets.token_hex(4)
    secret = secrets.token_hex(24)
    raw_key = f"{KEY_PREFIX}{identifier}_{secret}"
    return raw_key, f"{KEY_PREFIX}{identifier}", hash_api_key(raw_key)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def extract_prefix(raw_key: str) -> str | None:
    """The public prefix of a well-formed key, or None if the text is not shaped like a key."""
    match = _KEY_PATTERN.match(raw_key)
    return f"{KEY_PREFIX}{match.group(1)}" if match else None


def hashes_match(stored_hash: str, candidate_hash: str) -> bool:
    # Constant-time comparison, so response time does not reveal how many characters matched.
    return hmac.compare_digest(stored_hash, candidate_hash)