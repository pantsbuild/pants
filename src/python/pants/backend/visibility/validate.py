# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import Specs
from pants.base.specs_parser import SpecsParser
from pants.engine.addresses import Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSet,
    StringSequenceField,
    TargetGenerator,
    ValidatedDependencies,
    ValidateDependenciesRequest,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.strutil import bullet_list, pluralize, softwrap


class VisibilityViolationError(Exception):
    pass


class VisibilityField(StringSequenceField):
    alias = "visibility"
    default = ("::",)
    help = softwrap(
        """
        The `visibility` value takes a list of target specs that indicate which targets may or may
        not (using excludes) depend on this target.
        """
    )


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
    specs_parser = SpecsParser()
    targets_visibility_specs = {
        target: specs_parser.parse_specs(
            target.get(VisibilityField).value or (),
            unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
            convert_dir_literal_to_address_literal=False,
            description_of_origin=f"the visibility field on {target.address}",
        )
        for target in dependency_targets
    }

    targets_allowed_addresses = zip(
        targets_visibility_specs.keys(),
        await MultiGet(Get(Addresses, Specs, specs) for specs in targets_visibility_specs.values()),
    )

    # The target generator check for `invalid_deps` is to avoid issues like:
    #
    # pants.backend.visibility.validate.VisibilityViolationError: The following 1 target is not
    # visible to 3rdparty/python#pytest:
    #   * 3rdparty/python/requirements.txt has visibility: ::
    #
    invalid_deps = {
        (target, targets_visibility_specs[target])
        for target, allowed_addresses in targets_allowed_addresses
        if not isinstance(target, TargetGenerator)
        and request.field_set.address not in allowed_addresses
    }

    if not invalid_deps:
        return ValidatedDependencies()
    else:
        raise VisibilityViolationError(
            softwrap(
                f"""
                The following {pluralize(len(invalid_deps), "target")} {"is" if len(invalid_deps) ==
                1 else "are"} not visible to {request.field_set.address}:

                """
                + bullet_list(
                    f"""{dep.address} has visibility: {specs or "<none>"}"""
                    for dep, specs in invalid_deps
                )
            )
        )


def rules():
    return (
        *collect_rules(),
        UnionRule(ValidateDependenciesRequest, ValidateVisibilityRulesRequest),
    )
