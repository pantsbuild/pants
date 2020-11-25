# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Rules for the core Python target types.

This is a separate module to avoid circular dependencies. Note that all types used by call sites are
defined in `target_types.py`.
"""

import os.path

from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.target_types import (
    PexBinaryDefaults,
    PexBinaryDependencies,
    PexBinarySources,
    PexEntryPointField,
    PythonDistributionDependencies,
    PythonProvidesField,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    InjectDependenciesRequest,
    InjectedDependencies,
    InvalidFieldException,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import FilesNotFoundBehavior
from pants.source.source_root import SourceRoot, SourceRootRequest

# -----------------------------------------------------------------------------------------------
# `pex_binary` rules
# -----------------------------------------------------------------------------------------------


@rule
async def resolve_pex_entry_point(request: ResolvePexEntryPointRequest) -> ResolvedPexEntryPoint:
    entry_point_value = request.entry_point_field.value
    if entry_point_value and not entry_point_value.startswith(":"):
        if entry_point_value in ("<none>", "<None>"):
            return ResolvedPexEntryPoint(None)
        return ResolvedPexEntryPoint(entry_point_value)
    binary_source_paths = await Get(
        Paths, PathGlobs, request.sources.path_globs(FilesNotFoundBehavior.error)
    )
    if len(binary_source_paths.files) != 1:
        instructions_url = "https://www.pantsbuild.org/docs/python-package-goal#creating-a-pex-file-from-a-pex_binary-target"
        if not entry_point_value:
            raise InvalidFieldException(
                "Both the `entry_point` and `sources` fields are not set for the target "
                f"{request.sources.address}, so Pants cannot determine an entry point. Please "
                "either explicitly set the `entry_point` field and/or the `sources` field to "
                "exactly one file. You can set `entry_point='<none>' to leave off the entry point."
                f"See {instructions_url}."
            )
        else:
            raise InvalidFieldException(
                f"The `entry_point` field for the target {request.sources.address} is set to "
                f"the short-hand value {repr(entry_point_value)}, but the `sources` field is not "
                "set. Pants requires the `sources` field to expand the entry point to the "
                f"normalized form `path.to.module:{entry_point_value}`. Please either set the "
                "`sources` field to exactly one file or use a full value for `entry_point`. See "
                f"{instructions_url}."
            )
    entry_point_path = binary_source_paths.files[0]
    source_root = await Get(
        SourceRoot,
        SourceRootRequest,
        SourceRootRequest.for_file(entry_point_path),
    )
    stripped_source_path = os.path.relpath(entry_point_path, source_root.path)
    module_base, _ = os.path.splitext(stripped_source_path)
    normalized_path = module_base.replace(os.path.sep, ".")
    return ResolvedPexEntryPoint(
        f"{normalized_path}{entry_point_value}" if entry_point_value else normalized_path
    )


class InjectPexBinaryEntryPointDependency(InjectDependenciesRequest):
    inject_for = PexBinaryDependencies


@rule(desc="Inferring dependency from the pex_binary `entry_point` field")
async def inject_pex_binary_entry_point_dependency(
    request: InjectPexBinaryEntryPointDependency, pex_binary_defaults: PexBinaryDefaults
) -> InjectedDependencies:
    if not pex_binary_defaults.infer_dependencies:
        return InjectedDependencies()
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    entry_point = await Get(
        ResolvedPexEntryPoint,
        ResolvePexEntryPointRequest(
            original_tgt.target[PexEntryPointField], original_tgt.target[PexBinarySources]
        ),
    )
    if entry_point.val is None:
        return InjectedDependencies()
    module, _, _func = entry_point.val.partition(":")
    owners = await Get(PythonModuleOwners, PythonModule(module))
    # TODO: remove the check for == self once the `sources` field is removed.
    return InjectedDependencies(
        owner for owner in owners if owner != request.dependencies_field.address
    )


# -----------------------------------------------------------------------------------------------
# `python_distribution` rules
# -----------------------------------------------------------------------------------------------


class InjectPythonDistributionDependencies(InjectDependenciesRequest):
    inject_for = PythonDistributionDependencies


@rule
async def inject_python_distribution_dependencies(
    request: InjectPythonDistributionDependencies,
) -> InjectedDependencies:
    """Inject any `.with_binaries()` values, as it would be redundant to have to include in the
    `dependencies` field."""
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    with_binaries = original_tgt.target[PythonProvidesField].value.binaries
    if not with_binaries:
        return InjectedDependencies()
    # Note that we don't validate that these are all `pex_binary` targets; we don't care about
    # that here. `setup_py.py` will do that validation.
    addresses = await Get(
        Addresses,
        UnparsedAddressInputs(
            with_binaries.values(), owning_address=request.dependencies_field.address
        ),
    )
    return InjectedDependencies(addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectPexBinaryEntryPointDependency),
        UnionRule(InjectDependenciesRequest, InjectPythonDistributionDependencies),
    )
