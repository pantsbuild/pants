# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.engine.rules import Rule, collect_rules
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
