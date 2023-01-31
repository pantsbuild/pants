# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.dependency_inference.rules import import_rules
from pants.backend.python.framework.stevedore.target_types import (
    ResolvedStevedoreEntryPoints,
    ResolveStevedoreEntryPointsRequest,
    StevedoreEntryPoints,
    StevedoreEntryPointsField,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.engine.addresses import Address
from pants.engine.fs import GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    InvalidFieldException,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel

# -----------------------------------------------------------------------------------------------
# `StevedoreExtension` target rules
# -----------------------------------------------------------------------------------------------


@rule(
    desc="Determining the entry points for a `stevedore_extension` target",
    level=LogLevel.DEBUG,
)
async def resolve_stevedore_entry_points(
    request: ResolveStevedoreEntryPointsRequest,
) -> ResolvedStevedoreEntryPoints:
    # based on: pants.backend.python.target_types_rules.resolve_pex_entry_point

    # supported schemes mirror those in resolve_pex_entry_point:
    #  1) this does not support None, unlike pex_entry_point.
    #  2) `path.to.module` => preserve exactly.
    #  3) `path.to.module:func` => preserve exactly.
    #  4) `app.py` => convert into `path.to.app`.
    #  5) `app.py:func` => convert into `path.to.app:func`.

    address = request.entry_points_field.address

    # Use the engine to validate that any file exists
    entry_point_paths_results = await MultiGet(
        Get(
            Paths,
            PathGlobs(
                [os.path.join(address.spec_path, entry_point.value.module)],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"{address}'s `{request.entry_points_field.alias}` field",
            ),
        )
        for entry_point in request.entry_points_field.value
        if entry_point.value.module.endswith(".py")
    )

    # use iter so we can use next() below
    iter_entry_point_paths_results = iter(entry_point_paths_results)

    # We will have already raised if the glob did not match, i.e. if there were no files. But
    # we need to check if they used a file glob (`*` or `**`) that resolved to >1 file.
    #
    # It is clearer to iterate over entry_point_paths_results, but we need to include
    # the original glob in the error message, so we have to check for ".py" again.
    for entry_point in request.entry_points_field.value:
        # We only need paths/globs for this check. Ignore any modules.
        if not entry_point.value.module.endswith(".py"):
            continue

        entry_point_paths = next(iter_entry_point_paths_results)
        if len(entry_point_paths.files) != 1:
            raise InvalidFieldException(
                f"Multiple files matched for the `{request.entry_points_field.alias}` "
                f"{entry_point.value.spec!r} for the target {address}, but only one file expected. Are you using "
                f"a glob, rather than a file name?\n\n"
                f"All matching files: {list(entry_point_paths.files)}."
            )

    source_root_results = await MultiGet(
        Get(
            SourceRoot,
            SourceRootRequest,
            SourceRootRequest.for_file(entry_point_path.files[0]),
        )
        for entry_point_path in entry_point_paths_results
    )

    # use iter so we can use next() below
    iter_entry_point_paths_results = iter(entry_point_paths_results)
    iter_source_root_results = iter(source_root_results)

    resolved = []
    for entry_point in request.entry_points_field.value:
        # If it's already a module (cases #2 and #3), we'll just use that.
        # Otherwise, convert the file name into a module path (cases #4 and #5).
        if not entry_point.value.module.endswith(".py"):
            resolved.append(entry_point)
            continue

        entry_point_path = next(iter_entry_point_paths_results).files[0]
        source_root = next(iter_source_root_results)

        stripped_source_path = os.path.relpath(entry_point_path, source_root.path)
        module_base, _ = os.path.splitext(stripped_source_path)
        normalized_path = module_base.replace(os.path.sep, ".")
        resolved_ep_val = dataclasses.replace(entry_point.value, module=normalized_path)
        resolved.append(dataclasses.replace(entry_point, value=resolved_ep_val))
    return ResolvedStevedoreEntryPoints(StevedoreEntryPoints(resolved))


@dataclass(frozen=True)
class StevedoreEntryPointsInferenceFieldSet(FieldSet):
    required_fields = (StevedoreEntryPointsField, Dependencies, PythonResolveField)

    entry_points: StevedoreEntryPointsField
    dependencies: Dependencies
    resolve: PythonResolveField


class InferStevedoreExtensionDependencies(InferDependenciesRequest):
    infer_from = StevedoreEntryPointsInferenceFieldSet


@rule(
    desc="Inferring dependency from the stevedore_extension `entry_points` field",
    level=LogLevel.DEBUG,
)
async def infer_stevedore_entry_points_dependencies(
    request: InferStevedoreExtensionDependencies,
    python_setup: PythonSetup,
) -> InferredDependencies:
    entry_points: ResolvedStevedoreEntryPoints
    explicitly_provided_deps, entry_points = await MultiGet(
        Get(
            ExplicitlyProvidedDependencies,
            DependenciesRequest(request.field_set.dependencies),
        ),
        Get(
            ResolvedStevedoreEntryPoints,
            ResolveStevedoreEntryPointsRequest(request.field_set.entry_points),
        ),
    )
    if entry_points.val is None:
        return InferredDependencies(())
    address = request.field_set.address
    owners_per_entry_point = await MultiGet(
        Get(
            PythonModuleOwners,
            PythonModuleOwnersRequest(
                entry_point.value.module,
                resolve=request.field_set.resolve.normalized_value(python_setup),
            ),
        )
        for entry_point in entry_points.val
    )
    original_entry_points = request.field_set.entry_points.value
    resolved_owners: list[Address] = []
    for entry_point, owners, original_ep in zip(
        entry_points.val, owners_per_entry_point, original_entry_points
    ):
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            owners.ambiguous,
            address,
            import_reference="module",
            context=(
                f"The stevedore_extension target {address} has in its entry_points field "
                f'`"{entry_point.name}": "{repr(original_ep.value.spec)}"`,'
                f"which maps to the Python module `{entry_point.value.module}`"
            ),
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated(owners.ambiguous)
        unambiguous_owners = owners.unambiguous or (
            (maybe_disambiguated,) if maybe_disambiguated else ()
        )
        resolved_owners.extend(unambiguous_owners)
    return InferredDependencies(resolved_owners)


def rules():
    return [
        *collect_rules(),
        *import_rules(),
        UnionRule(InferDependenciesRequest, InferStevedoreExtensionDependencies),
    ]
