# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.tools.semgrep.target_types import SemgrepRuleSourceField
from pants.build_graph.address import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    AllTargets,
    Dependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    SingleSourceField,
    Target,
)
from pants.engine.unions import UnionRule

# class SemgrepDependenciesField(SpecialCasedDependencies):
#     alias = "semgrep_dependencies"
#     default = ()
#     help = "Which semgrep rules to use for this file"


class SemgrepDependencyInferenceFieldSet(FieldSet):
    required_fields = (SingleSourceField, Dependencies)

    source = SingleSourceField
    dependencies = Dependencies


@dataclass(frozen=True)
class InferSemgrepDependenciesRequest(InferDependenciesRequest):
    infer_from = SemgrepDependencyInferenceFieldSet


@dataclass
class AllSemgrepConfigs:
    targets: dict[str, list[Target]]


@rule
async def find_all_semgrep_configs(all_targets: AllTargets) -> AllSemgrepConfigs:
    targets = defaultdict(list)
    for tgt in all_targets:
        if tgt.has_field(SemgrepRuleSourceField):
            targets[tgt.address.spec_path].append(tgt)
    return AllSemgrepConfigs(targets)


@rule
async def infer_semgrep_dependencies(
    request: InferSemgrepDependenciesRequest, all_semgrep: AllSemgrepConfigs
) -> InferredDependencies:
    spec = request.field_set.address.spec_path
    found: list[Address] = []

    while True:
        found.extend(tgt.address for tgt in all_semgrep.targets.get(spec, []))

        if not spec:
            break

        spec = os.path.dirname(spec)

    return InferredDependencies(include=found)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferSemgrepDependenciesRequest),
        # Target.register_plugin_field(SemgrepDependenciesField), #
    ]
