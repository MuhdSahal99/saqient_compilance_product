"""Field-level encryption for sensitive values (TRN, IBAN, national id).

AES-256-GCM with a random 96-bit nonce. The associated data binds each
ciphertext to its organisation and field, so a value copied into another
tenant's row or another column fails to decrypt. Stored form:
``v1:<base64(nonce || ciphertext)>``. Plaintext is never logged.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_PREFIX = "v1:"


class FieldCryptoError(RuntimeError):
    pass


@lru_cache
def _key() -> bytes:
    s = get_settings()
    if s.field_encryption_key:
        key = base64.b64decode(s.field_encryption_key)
        if len(key) != 32:
            raise FieldCryptoError("FIELD_ENCRYPTION_KEY must be 32 bytes, base64-encoded")
        return key
    # Development/test only: derive from SECRET_KEY. Production refuses this (config guard).
    return hashlib.sha256(b"saqient-field-key:" + s.secret_key.encode()).digest()


def _aad(org_id: uuid.UUID, field: str) -> bytes:
    return f"{org_id}:{field}".encode()


def encrypt_field(value: str, *, org_id: uuid.UUID, field: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), _aad(org_id, field))
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_field(token: str, *, org_id: uuid.UUID, field: str) -> str:
    if not token.startswith(_PREFIX):
        raise FieldCryptoError("unknown ciphertext version")
    raw = base64.b64decode(token[len(_PREFIX) :])
    try:
        return AESGCM(_key()).decrypt(raw[:12], raw[12:], _aad(org_id, field)).decode("utf-8")
    except InvalidTag as exc:
        raise FieldCryptoError("cannot decrypt field") from exc


def mask(value: str, visible: int = 4) -> str:
    if len(value) <= visible:
        return "•" * len(value)
    return "•" * (len(value) - visible) + value[-visible:]
