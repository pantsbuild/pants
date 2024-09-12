#!/usr/bin/env python3
import hashlib

from pants.engine.internals.native_engine import Digest

def dummy_digest(value: str) -> Digest:
    hex_digest = hashlib.sha256(value.encode("utf8")).hexdigest()
    return Digest(hex_digest, 0)
