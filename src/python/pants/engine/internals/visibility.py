# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.target_types import DefaultsRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSet,
    Targets,
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
    targets_defaults = await MultiGet(
        Get(Targets, DefaultsRequest, DefaultsRequest.for_target(tgt, "visibility"))
        for tgt in dependency_targets
    )
    subject = request.field_set.address
    for target, defaults in zip(dependency_targets, targets_defaults):
        if defaults:
            default_visibility = defaults[0].get(VisibilityField).value
            default_origin = defaults[0]
        else:
            default_visibility = (VisibilityField.PUBLIC_VISIBILITY,)
            default_origin = target
        visibility_field = target.get(VisibilityField)
        if visibility_field.value is not None:
            origin = target
        else:
            origin = default_origin
        if not visibility_field.visible(origin.address, subject, default=default_visibility):
            raise VisibilityViolationError(
                softwrap(
                    f"""
                    {target.address} is not visible to {subject}.

                    Visibility from {origin.alias} {origin.address} : \
                    {", ".join(visibility_field.get_visibility(default_visibility) or ("<none>",))}.
                    """
                )
            )
    return ValidatedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(ValidateDependenciesRequest, ValidateVisibilityRulesRequest),
    )
