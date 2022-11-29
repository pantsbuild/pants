# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.visibility import lint
from pants.backend.visibility import rules as visibility


def rules():
    return (
        *visibility.rules(),
        *lint.rules(),
    )
