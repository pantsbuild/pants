# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSet,
    ValidatedDependencies,
    ValidateDependenciesRequest,
    VisibilityField,
    VisibilityViolationError,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap


class ValidateVisibilityRulesFieldSet(FieldSet):
    required_fields = (VisibilityField,)


class ValidateVisibilityRulesRequest(ValidateDependenciesRequest):
    field_set_type = ValidateVisibilityRulesFieldSet


@rule
async def validate_visibility_rules(
    request: ValidateVisibilityRulesRequest,
) -> ValidatedDependencies:
    wrapped_dependency_targets = await MultiGet(
        Get(WrappedTarget, WrappedTargetRequest(address, description_of_origin="<infallible>"))
        for address in request.dependencies
    )
    dependency_targets = [wrapped.target for wrapped in wrapped_dependency_targets]
    to_address = request.field_set.address
    for target in dependency_targets:
        visibility_field = target.get(VisibilityField)
        if not visibility_field.visible(to_address):
            raise VisibilityViolationError(
                softwrap(
                    f"""
                    {target.address} is not visible to {to_address}.

                    Visibility for {target.alias} {target.address} : \
                    {", ".join(visibility_field.value or ("<none>",))}.
                    """
                )
            )
    return ValidatedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(ValidateDependenciesRequest, ValidateVisibilityRulesRequest),
    )
