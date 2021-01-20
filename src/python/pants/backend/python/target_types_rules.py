# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Rules for the core Python target types.

This is a separate module to avoid circular dependencies. Note that all types used by call sites are
defined in `target_types.py`.
"""

import os.path

from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.dependency_inference.rules import PythonInferSubsystem, import_rules
from pants.backend.python.target_types import (
    PexBinaryDependencies,
    PexEntryPointField,
    PythonDistributionDependencies,
    PythonProvidesField,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.fs import GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    InjectDependenciesRequest,
    InjectedDependencies,
    InvalidFieldException,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import docs_url

# -----------------------------------------------------------------------------------------------
# `pex_binary` rules
# -----------------------------------------------------------------------------------------------


@rule(desc="Determining the entry point for a `pex_binary` target")
async def resolve_pex_entry_point(request: ResolvePexEntryPointRequest) -> ResolvedPexEntryPoint:
    ep_val = request.entry_point_field.value
    ep_alias = request.entry_point_field.alias
    address = request.entry_point_field.address

    # TODO: factor up some of this code between python_awslambda and pex_binary once `sources` is
    #  removed.

    # This code is tricky, as we support several different schemes:
    #  1) `<none>` or `<None>` => set to `None`.
    #  2) `path.to.module` => preserve exactly.
    #  3) `path.to.module:func` => preserve exactly.
    #  4) `app.py` => convert into `path.to.app`.
    #  5) `app.py:func` => convert into `path.to.app:func`.

    if ep_val is None:
        instructions_url = docs_url(
            "python-package-goal#creating-a-pex-file-from-a-pex_binary-target"
        )
        raise InvalidFieldException(
            f"The `{ep_alias}` field is not set for the target {address}. Run "
            f"`./pants help pex_binary` for more information on how to set the field or "
            f"see {instructions_url}."
        )

    # Case #1.
    if ep_val in ("<none>", "<None>"):
        return ResolvedPexEntryPoint(None)

    path, _, func = ep_val.partition(":")

    # If it's already a module (cases #2 and #3), simply use that. Otherwise, convert the file name
    # into a module path (cases #4 and #5).
    if not path.endswith(".py"):
        return ResolvedPexEntryPoint(ep_val)

    # Use the engine to validate that the file exists and that it resolves to only one file.
    full_glob = os.path.join(address.spec_path, path)
    entry_point_paths = await Get(
        Paths,
        PathGlobs(
            [full_glob],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{address}'s `{request.entry_point_field.alias}` field",
        ),
    )
    # We will have already raised if the glob did not match, i.e. if there were no files. But
    # we need to check if they used a file glob (`*` or `**`) that resolved to >1 file.
    if len(entry_point_paths.files) != 1:
        raise InvalidFieldException(
            f"Multiple files matched for the `{ep_alias}` {repr(ep_val)} for the target "
            f"{address}, but only one file expected. Are you using a glob, rather than a file "
            f"name?\n\nAll matching files: {list(entry_point_paths.files)}."
        )
    entry_point_path = entry_point_paths.files[0]
    source_root = await Get(
        SourceRoot,
        SourceRootRequest,
        SourceRootRequest.for_file(entry_point_path),
    )
    stripped_source_path = os.path.relpath(entry_point_path, source_root.path)
    module_base, _ = os.path.splitext(stripped_source_path)
    normalized_path = module_base.replace(os.path.sep, ".")
    return ResolvedPexEntryPoint(f"{normalized_path}:{func}" if func else normalized_path)


class InjectPexBinaryEntryPointDependency(InjectDependenciesRequest):
    inject_for = PexBinaryDependencies


@rule(desc="Inferring dependency from the pex_binary `entry_point` field")
async def inject_pex_binary_entry_point_dependency(
    request: InjectPexBinaryEntryPointDependency, python_infer_subsystem: PythonInferSubsystem
) -> InjectedDependencies:
    if not python_infer_subsystem.entry_points:
        return InjectedDependencies()
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    entry_point = await Get(
        ResolvedPexEntryPoint,
        ResolvePexEntryPointRequest(original_tgt.target[PexEntryPointField]),
    )
    if entry_point.val is None:
        return InjectedDependencies()
    module, _, _func = entry_point.val.partition(":")
    owners = await Get(PythonModuleOwners, PythonModule(module))
    return InjectedDependencies(owners)


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
        *import_rules(),
        UnionRule(InjectDependenciesRequest, InjectPexBinaryEntryPointDependency),
        UnionRule(InjectDependenciesRequest, InjectPythonDistributionDependencies),
    )
