"""Bounded source identity keys without truncating distinguishing source characters."""

from hashlib import sha256
from uuid import UUID


def source_identity_key(binding_id: UUID, business_key: str) -> str:
    readable = f"binding:{binding_id}:{business_key}"
    if len(readable) <= 256:
        return readable
    # A separate namespace avoids collisions with a literal source key that looks
    # like a digest. Canonical UUID derivation still uses the complete source key.
    return f"binding-sha256:{binding_id}:{sha256(business_key.encode('utf-8')).hexdigest()}"
