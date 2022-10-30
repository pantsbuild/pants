# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.internals.target_adaptor import TargetAdaptor, TargetAdaptorRequest
from pants.engine.internals.visibility import (
    BuildFileVisibility,
    BuildFileVisibilityImplementation,
    BuildFileVisibilityImplementationRequest,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    FieldSet,
    ValidatedDependencies,
    ValidateDependenciesRequest,
)
from pants.engine.unions import UnionRule


class DefaultBuildFileVisibilityImplementationRequest(BuildFileVisibilityImplementationRequest):
    pass


class VisibilityValidateFieldSet(FieldSet):
    required_fields = (Dependencies,)


class VisibilityValidateDependenciesRequest(ValidateDependenciesRequest):
    field_set_type = VisibilityValidateFieldSet


@rule
def default_build_file_visibility_implementation(
    _: DefaultBuildFileVisibilityImplementationRequest,
) -> BuildFileVisibilityImplementation:
    return BuildFileVisibilityImplementation(BuildFileVisibility)


@rule
async def visibility_validate_dependencies(
    request: VisibilityValidateDependenciesRequest,
) -> ValidatedDependencies:
    address = request.field_set.address.maybe_convert_to_target_generator()
    _ = await MultiGet(
        Get(
            TargetAdaptor,
            TargetAdaptorRequest(
                address=dependency_address.maybe_convert_to_target_generator(),
                address_of_origin=address,
                description_of_origin=(
                    f"dependency validation of {request.field_set.address} on {dependency_address}"
                ),
            ),
        )
        for dependency_address in request.dependencies
    )
    return ValidatedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(
            BuildFileVisibilityImplementationRequest,
            DefaultBuildFileVisibilityImplementationRequest,
        ),
        UnionRule(ValidateDependenciesRequest, VisibilityValidateDependenciesRequest),
    )
