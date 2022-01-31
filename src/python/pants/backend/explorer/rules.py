# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.rules import QueryRule
from pants.engine.target import AllTargets


def rules():
    return (QueryRule(AllTargets, ()),)
