# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Rules for the core Python target types.

This is a separate module to avoid circular dependencies. Note that all types used by call sites are
defined in `target_types.py`.
"""

import dataclasses
import os.path
from collections import defaultdict

from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.dependency_inference.rules import PythonInferSubsystem, import_rules
from pants.backend.python.target_types import (
    EntryPoint,
    PexBinaryDependencies,
    PexEntryPointField,
    PythonDistributionDependencies,
    PythonDistributionEntryPoints,
    PythonProvidesField,
    ResolvedPexEntryPoint,
    ResolvedPythonDistributionEntryPoints,
    ResolvePexEntryPointRequest,
    ResolvePythonDistributionEntryPointsRequest,
)
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.fs import GlobMatchErrorBehavior, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    InvalidFieldException,
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.frozendict import FrozenDict

# -----------------------------------------------------------------------------------------------
# `pex_binary` rules
# -----------------------------------------------------------------------------------------------


@rule(desc="Determining the entry point for a `pex_binary` target")
async def resolve_pex_entry_point(request: ResolvePexEntryPointRequest) -> ResolvedPexEntryPoint:
    ep_val = request.entry_point_field.value
    address = request.entry_point_field.address

    # We support several different schemes:
    #  1) `<none>` or `<None>` => set to `None`.
    #  2) `path.to.module` => preserve exactly.
    #  3) `path.to.module:func` => preserve exactly.
    #  4) `app.py` => convert into `path.to.app`.
    #  5) `app.py:func` => convert into `path.to.app:func`.

    # Case #1.
    if ep_val.module in ("<none>", "<None>"):
        return ResolvedPexEntryPoint(None, file_name_used=False)

    # If it's already a module (cases #2 and #3), simply use that. Otherwise, convert the file name
    # into a module path (cases #4 and #5).
    if not ep_val.module.endswith(".py"):
        return ResolvedPexEntryPoint(ep_val, file_name_used=False)

    # Use the engine to validate that the file exists and that it resolves to only one file.
    full_glob = os.path.join(address.spec_path, ep_val.module)
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
            f"Multiple files matched for the `{request.entry_point_field.alias}` "
            f"{ep_val.spec!r} for the target {address}, but only one file expected. Are you using "
            f"a glob, rather than a file name?\n\n"
            f"All matching files: {list(entry_point_paths.files)}."
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
    return ResolvedPexEntryPoint(
        dataclasses.replace(ep_val, module=normalized_path), file_name_used=True
    )


class InjectPexBinaryEntryPointDependency(InjectDependenciesRequest):
    inject_for = PexBinaryDependencies


@rule(desc="Inferring dependency from the pex_binary `entry_point` field")
async def inject_pex_binary_entry_point_dependency(
    request: InjectPexBinaryEntryPointDependency, python_infer_subsystem: PythonInferSubsystem
) -> InjectedDependencies:
    if not python_infer_subsystem.entry_points:
        return InjectedDependencies()
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    explicitly_provided_deps, entry_point = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(original_tgt.target[Dependencies])),
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(original_tgt.target[PexEntryPointField]),
        ),
    )
    if entry_point.val is None:
        return InjectedDependencies()
    owners = await Get(PythonModuleOwners, PythonModule(entry_point.val.module))
    address = original_tgt.target.address
    explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
        owners.ambiguous,
        address,
        # If the entry point was specified as a file, like `app.py`, we know the module must
        # live in the pex_binary's directory or subdirectory, so the owners must be ancestors.
        owners_must_be_ancestors=entry_point.file_name_used,
        import_reference="module",
        context=(
            f"The pex_binary target {address} has the field "
            f"`entry_point={repr(original_tgt.target[PexEntryPointField].value.spec)}`, which "
            f"maps to the Python module `{entry_point.val.module}`"
        ),
    )
    maybe_disambiguated = explicitly_provided_deps.disambiguated(
        owners.ambiguous, owners_must_be_ancestors=entry_point.file_name_used
    )
    unambiguous_owners = owners.unambiguous or (
        (maybe_disambiguated,) if maybe_disambiguated else ()
    )
    return InjectedDependencies(unambiguous_owners)


# -----------------------------------------------------------------------------------------------
# `python_distribution` rules
# -----------------------------------------------------------------------------------------------


@rule(desc="Determining the entry points for a `python_distribution` target")
async def resolve_python_distribution_entry_points(
    request: ResolvePythonDistributionEntryPointsRequest,
) -> ResolvedPythonDistributionEntryPoints:
    field_value = request.entry_points_field.value
    if field_value is None:
        return ResolvedPythonDistributionEntryPoints(None)

    address = request.entry_points_field.address
    entry_points: dict[str, dict[str, EntryPoint]] = defaultdict(dict)

    for section, values in field_value.items():
        for name, ref in values.items():
            if ref.startswith(":") or "/" in ref:
                targets = await Get(Targets, UnparsedAddressInputs([ref], owning_address=address))
                if not targets:
                    raise InvalidFieldException(
                        f'The "entry_points" target address {repr(ref)} does not resolve to any known target.'
                    )

                for target in targets:
                    if target.has_field(PexEntryPointField):
                        binary_entry_point = await Get(
                            ResolvedPexEntryPoint,
                            ResolvePexEntryPointRequest(target[PexEntryPointField]),
                        )
                        ep = binary_entry_point.val
                        break
                else:
                    raise InvalidFieldException(
                        f'The "entry_points" target address {repr(ref)} does not resolve to a pex_binary() target, but:'
                        + ", ".join(str(t) for t in targets)
                    )
            else:
                ep = EntryPoint.parse(ref, f"{name} for {address} {section}")

            if ep is not None:
                entry_points[section][name] = ep

    return ResolvedPythonDistributionEntryPoints(
        FrozenDict({key: FrozenDict(value) for key, value in entry_points.items()})
    )


class InjectPythonDistributionDependencies(InjectDependenciesRequest):
    inject_for = PythonDistributionDependencies


@rule
async def inject_python_distribution_dependencies(
    request: InjectPythonDistributionDependencies, python_infer_subsystem: PythonInferSubsystem
) -> InjectedDependencies:
    """Inject dependencies that we can infer from entry points in the distribution.

    Inject module owners referred to from `entry_points`.

    Inject any `.with_binaries()` values, as it would be redundant to have to
    include in the `dependencies` field.
    """
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)

    entry_points = await Get(
        ResolvedPythonDistributionEntryPoints,
        ResolvePythonDistributionEntryPointsRequest(
            original_tgt.target[PythonDistributionEntryPoints]
        ),
    )
    entry_point_addresses = Addresses()

    if entry_points.val and python_infer_subsystem.entry_points:
        address = original_tgt.target.address
        explicitly_provided_deps = await Get(
            ExplicitlyProvidedDependencies, DependenciesRequest(original_tgt.target[Dependencies])
        )
        all_entry_points = [
            (key, name, entry_point)
            for key, section in entry_points.val.items()
            for name, entry_point in section.items()
        ]
        all_owners = await MultiGet(
            Get(PythonModuleOwners, PythonModule(entry_point.module))
            for _, _, entry_point in all_entry_points
        )
        for (key, name, entry_point), owners in zip(all_entry_points, all_owners):
            field_str = repr({key: {name: entry_point.spec}})
            explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                owners.ambiguous,
                address,
                import_reference="module",
                context=(
                    f"The distribution target {address} has the field "
                    f"`entry_points={field_str}`"
                ),
            )
            maybe_disambiguated = explicitly_provided_deps.disambiguated_via_ignores(
                owners.ambiguous
            )
            unambiguous_owners = Addresses(
                owners.unambiguous
                or ((maybe_disambiguated,) if maybe_disambiguated else Addresses())
            )
            entry_point_addresses += unambiguous_owners  # type: ignore[assignment]

    with_binaries = original_tgt.target[PythonProvidesField].value.binaries
    if not with_binaries:
        pex_addresses = Addresses()
    else:
        # Note that we don't validate that these are all `pex_binary` targets; we don't care about
        # that here. `setup_py.py` will do that validation.
        pex_addresses = await Get(
            Addresses,
            UnparsedAddressInputs(
                with_binaries.values(), owning_address=request.dependencies_field.address
            ),
        )

    return InjectedDependencies(entry_point_addresses + pex_addresses)


def rules():
    return (
        *collect_rules(),
        *import_rules(),
        UnionRule(InjectDependenciesRequest, InjectPexBinaryEntryPointDependency),
        UnionRule(InjectDependenciesRequest, InjectPythonDistributionDependencies),
    )
