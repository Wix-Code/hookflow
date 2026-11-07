"""Webhook signing secrets.

HookFlow must be able to read a secret again later (to sign each delivery), so unlike a password it cannot be
hashed. It is encrypted instead (Fernet: AES with an integrity check). The database alone is then not enough to
read the secrets: an attacker would also need ENCRYPTION_KEY from the server's environment.
"""

import secrets
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import Settings

SECRET_PREFIX = "whsec_"


def generate_signing_secret() -> str:
    return f"{SECRET_PREFIX}{secrets.token_hex(24)}"


@lru_cache
def _fernet(key: str) -> Fernet:
    return Fernet(key.encode("utf-8"))


def encrypt_secret(plain_text: str, settings: Settings) -> str:
    return _fernet(settings.encryption_key).encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str, settings: Settings) -> str:
    return _fernet(settings.encryption_key).decrypt(token.encode("utf-8")).decode("utf-8")