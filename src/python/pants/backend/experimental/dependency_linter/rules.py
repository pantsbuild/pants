# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.backend.experimental.dependency_linter.target_types import (
    AllowedTargetsField,
    TargetField,
)
from pants.base.specs import Specs
from pants.base.specs_parser import SpecsParser
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.engine.addresses import Addresses
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, FieldSet, Targets
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


@dataclass(frozen=True)
class DependencyRuleFieldSet(FieldSet):
    required_fields = (Dependencies,)

    dependencies: Dependencies


class AllowedDependencies(FrozenDict[str, FrozenOrderedSet[str]]):
    def __init__(self, mapping: Mapping[str, OrderedSet[str]]) -> None:
        super().__init__({key: FrozenOrderedSet(value) for key, value in mapping.items()})


class DependencyRuleCheckRequest(LintTargetsRequest):
    field_set_type = DependencyRuleFieldSet
    name = "dependency_linter_check"


@rule
async def build_allowed_dependencies(targets: Targets) -> AllowedDependencies:
    rules = [tgt for tgt in targets if tgt.has_field(TargetField)]

    specs_parser = SpecsParser()
    allowed_dependencies: Mapping[str, OrderedSet[str]] = defaultdict(OrderedSet[str])
    for dependency_rule in rules:
        target_field = dependency_rule.get(TargetField).value
        if target_field is None:
            continue

        target_specs = specs_parser.parse_specs(
            [target_field],
            description_of_origin="the target from dependency_rule",
            convert_dir_literal_to_address_literal=False,
        )
        allowed_targets_specs = specs_parser.parse_specs(
            dependency_rule.get(AllowedTargetsField).value or [],
            description_of_origin="the allowed_targets from dependency_rule",
            convert_dir_literal_to_address_literal=False,
        )
        targets, allowed_targets = await MultiGet(
            Get(Targets, Specs, target_specs),
            Get(
                Targets,
                Specs,
                allowed_targets_specs,
            ),
        )
        allowed_target_addresses = [t.address.spec for t in allowed_targets]

        for target in targets:
            allowed_dependencies[target.address.spec].update(allowed_target_addresses)

    return AllowedDependencies(allowed_dependencies)


@rule
async def check_field_set(
    all_allowed_dependencies: AllowedDependencies, field_set: DependencyRuleFieldSet
) -> LintResult:
    address = field_set.address.spec
    dependencies = await Get(Addresses, DependenciesRequest(field_set.dependencies))

    allowed_dependencies = all_allowed_dependencies.get(address)

    exit_code = 0
    stderr: list[str] = []

    if len(dependencies) == 0:
        return LintResult(exit_code=0, stderr="\n".join(stderr), stdout="")

    if allowed_dependencies is None:
        stderr.append(f"No dependencies are allowed for '{address}'")
        return LintResult(exit_code=1, stderr="\n".join(stderr), stdout="")

    for dependency in dependencies:
        if dependency.spec not in allowed_dependencies:
            exit_code = 1
            stderr.append(f"Dependency '{dependency.spec}' is not allowed for '{address}'")

    return LintResult(exit_code=exit_code, stderr="\n".join(stderr), stdout="")


@rule
async def run_dependency_linter_check(request: DependencyRuleCheckRequest) -> LintResults:
    results = await MultiGet(
        Get(LintResult, DependencyRuleFieldSet, fs) for fs in request.field_sets
    )

    return LintResults(linter_name=request.name, results=results)


def rules():
    return [
        *collect_rules(),
        UnionRule(LintTargetsRequest, DependencyRuleCheckRequest),
    ]
