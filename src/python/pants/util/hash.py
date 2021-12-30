# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import json
from collections import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from functools import partial
from typing import Any


class JsonEncoder(json.JSONEncoder):
    """Allow us to serialize everything, with a fallback on `str()` in case of any esoteric
    types."""

    def default(self, o):
        """Return a serializable object for o."""
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, Mapping):
            return dict(o)
        if isinstance(o, Sequence):
            return list(o)
        try:
            return super().default(o)
        except TypeError:
            return str(o)


json_dumps = partial(
    json.dumps, indent=None, separators=(",", ":"), sort_keys=True, cls=JsonEncoder
)


def get_hash(value: Any, *, name: str = "sha256") -> hashlib._Hash:
    return hashlib.new(name, json_dumps(value).encode("utf-8"))
