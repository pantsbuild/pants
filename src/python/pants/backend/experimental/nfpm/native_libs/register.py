# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Analyze contents of nfpm-generated system packages to auto-generate deps from native lib deps."""

from __future__ import annotations

from collections.abc import Iterable

from pants.backend.nfpm.native_libs.rules import rules as native_libs_rules
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *native_libs_rules(),
    ]
