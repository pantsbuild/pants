# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.engine.rules import collect_rules, rule


@dataclass(frozen=True)
class GoBuildContext:
    """Build-related options. Those options are centralized in this dataclass so that configuration options can be
    merged with any override values from relevant target fields."""
    cgo_allowed: bool


@rule
async def go_global_context(golang_subsystem: GolangSubsystem) -> GoBuildContext:
    return GoBuildContext(cgo_allowed=golang_subsystem.cgo_allowed)


def rules():
    return collect_rules()
