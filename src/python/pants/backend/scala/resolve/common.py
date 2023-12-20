# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.scala.target_types import AllScalaTargets
from pants.engine.rules import collect_rules, rule
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.util.ordered_set import FrozenOrderedSet


class AllScalaResolves(FrozenOrderedSet[str]):
    pass


@rule
async def get_all_scala_resolves(
    jvm_artifact_targets: AllScalaTargets, jvm: JvmSubsystem
) -> AllScalaResolves:
    resolve_names = sorted(
        [tgt[JvmResolveField].normalized_value(jvm) for tgt in jvm_artifact_targets]
    )
    return AllScalaResolves(resolve_names)


def rules():
    return collect_rules()
