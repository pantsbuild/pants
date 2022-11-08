# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesImplementation,
    BuildFileDependencyRulesImplementationRequest,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRuleAction,
    DependenciesRuleActionRequest,
    FieldSet,
    ValidatedDependencies,
    ValidateDependenciesRequest,
)
from pants.engine.unions import UnionRule


class BuildFileVisibilityImplementationRequest(BuildFileDependencyRulesImplementationRequest):
    pass


class VisibilityValidateFieldSet(FieldSet):
    required_fields = (Dependencies,)


class VisibilityValidateDependenciesRequest(ValidateDependenciesRequest):
    field_set_type = VisibilityValidateFieldSet


@rule
def build_file_visibility_implementation(
    _: BuildFileVisibilityImplementationRequest,
) -> BuildFileDependencyRulesImplementation:
    return BuildFileDependencyRulesImplementation(BuildFileDependencyRules)


@rule
async def visibility_validate_dependencies(
    request: VisibilityValidateDependenciesRequest,
) -> ValidatedDependencies:
    address = request.field_set.address
    dependencies_rule_action = await Get(
        DependenciesRuleAction,
        DependenciesRuleActionRequest(
            address=address,
            dependencies=request.dependencies,
            description_of_origin=f"get dependency rules for {address}",
        ),
    )
    dependencies_rule_action.execute_actions()
    return ValidatedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(
            BuildFileDependencyRulesImplementationRequest,
            BuildFileVisibilityImplementationRequest,
        ),
        UnionRule(ValidateDependenciesRequest, VisibilityValidateDependenciesRequest),
    )
