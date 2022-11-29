# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.visibility.subsystem import VisibilitySubsystem
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST
from pants.engine.internals.dep_rules import DependencyRuleActionDeniedError
from pants.engine.internals.session import RunId
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, ProcessResultMetadata
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    DependenciesRuleApplication,
    DependenciesRuleApplicationRequest,
    FieldSet,
)
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class VisibilityFieldSet(FieldSet):
    required_fields = (Dependencies,)
    dependencies: Dependencies


class EnforceVisibilityRules(LintTargetsRequest):
    tool_subsystem = VisibilitySubsystem
    field_set_type = VisibilityFieldSet
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Enforce visibility rules", level=LogLevel.DEBUG)
async def enforce_visibility_rules(
    request: EnforceVisibilityRules.Batch, platform: Platform, run_id: RunId
) -> LintResult:
    all_dependencies = await MultiGet(
        Get(Addresses, DependenciesRequest(field_set.dependencies, include_special_cased_deps=True))
        for field_set in request.elements
    )
    all_dependencies_rule_action = await MultiGet(
        Get(
            DependenciesRuleApplication,
            DependenciesRuleApplicationRequest(
                address=field_set.address,
                dependencies=dependencies,
                description_of_origin=f"get dependency rules for {field_set.address}",
            ),
        )
        for field_set, dependencies in zip(request.elements, all_dependencies)
    )

    violations = []
    try:
        for deps_rule_action in all_dependencies_rule_action:
            deps_rule_action.execute_actions()
    except DependencyRuleActionDeniedError as e:
        violations.append(str(e))

    # Mimic a process result to pass as lint result.
    result = FallibleProcessResult(
        stdout="\n\n".join(violations).encode(),
        stdout_digest=EMPTY_FILE_DIGEST,
        stderr=b"",
        stderr_digest=EMPTY_FILE_DIGEST,
        exit_code=0 if not violations else 1,
        output_digest=EMPTY_DIGEST,
        platform=platform,
        metadata=ProcessResultMetadata(None, "ran_locally", run_id),
    )
    return LintResult.create(request, process_result=result)


def rules():
    return (
        *collect_rules(),
        *EnforceVisibilityRules.rules(),
    )
