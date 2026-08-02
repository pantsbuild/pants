# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.embedded_binary import get_embedded_binary


def pants_lock_bin() -> str:
    """Return the path to the bundled pants_lock binary, or raise if not present."""
    ret = get_embedded_binary("pants_lock")
    if ret is None:
        # Should never happen if our build is sound.
        raise Exception("Could not find the pants_lock binary")
    return ret
