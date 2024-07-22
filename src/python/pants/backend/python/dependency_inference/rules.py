# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Dict, Iterable, Optional

from pants.backend.python.dependency_inference import module_mapper, parse_python_dependencies
from pants.backend.python.dependency_inference.default_unowned_dependencies import (
    DEFAULT_UNOWNED_DEPENDENCIES,
)
from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
    ResolveName,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonAssetPaths,
    ParsedPythonDependencies,
    ParsedPythonImports,
    ParsePythonDependenciesRequest,
)
from pants.backend.python.dependency_inference.subsystem import (
    AmbiguityResolution,
    InitFilesInference,
    PythonInferSubsystem,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonDependenciesField,
    PythonResolveField,
    PythonSourceField,
    PythonTestSourceField,
)
from pants.backend.python.util_rules import ancestor_files, pex
from pants.backend.python.util_rules.ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core import target_types
from pants.core.target_types import AllAssetTargetsByPath
from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.unowned_dependency_behavior import (
    UnownedDependencyError,
    UnownedDependencyUsage,
)
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import Get, MultiGet, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.docutil import doc_url
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PythonImportDependenciesInferenceFieldSet(FieldSet):
    required_fields = (
        PythonSourceField,
        PythonDependenciesField,
        PythonResolveField,
        InterpreterConstraintsField,
    )

    source: PythonSourceField
    dependencies: PythonDependenciesField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField


class InferPythonImportDependencies(InferDependenciesRequest):
    infer_from = PythonImportDependenciesInferenceFieldSet


def _get_inferred_asset_deps(
    address: Address,
    request_file_path: str,
    assets_by_path: AllAssetTargetsByPath,
    assets: ParsedPythonAssetPaths,
    explicitly_provided_deps: ExplicitlyProvidedDependencies,
) -> dict[str, ImportResolveResult]:
    def _resolve_single_asset(filepath) -> ImportResolveResult:
        # NB: Resources in Python's ecosystem are loaded relative to a package, so we only try and
        # query for a resource relative to requesting module's path
        # (I.e. we assume the user is doing something like `pkgutil.get_data(__file__, "foo/bar")`)
        # See https://docs.python.org/3/library/pkgutil.html#pkgutil.get_data
        # and Pants' own docs on resources.
        #
        # Files in Pants are always loaded relative to the build root without any source root
        # stripping, so we use the full filepath to query for files.
        # (I.e. we assume the user is doing something like `open("src/python/configs/prod.json")`)
        #
        # In either case we could also try and query based on the others' key, however this will
        # almost always lead to a false positive.
        resource_path = PurePath(request_file_path).parent / filepath
        file_path = PurePath(filepath)

        inferred_resource_tgts = assets_by_path.resources.get(resource_path, frozenset())
        inferred_file_tgts = assets_by_path.files.get(file_path, frozenset())
        inferred_tgts = inferred_resource_tgts | inferred_file_tgts

        if inferred_tgts:
            possible_addresses = tuple(tgt.address for tgt in inferred_tgts)
            if len(possible_addresses) == 1:
                return ImportResolveResult(ImportOwnerStatus.unambiguous, possible_addresses)

            explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                possible_addresses,
                address,
                import_reference="asset",
                context=f"The target {address} uses `{filepath}`",
            )
            maybe_disambiguated = explicitly_provided_deps.disambiguated(possible_addresses)
            if maybe_disambiguated:
                return ImportResolveResult(ImportOwnerStatus.disambiguated, (maybe_disambiguated,))
            else:
                return ImportResolveResult(ImportOwnerStatus.ambiguous)
        else:
            return ImportResolveResult(ImportOwnerStatus.unowned)

    return {filepath: _resolve_single_asset(filepath) for filepath in assets}


class ImportOwnerStatus(Enum):
    unambiguous = "unambiguous"
    disambiguated = "disambiguated"
    ambiguous = "ambiguous"
    unowned = "unowned"
    weak_ignore = "weak_ignore"
    unownable = "unownable"


@dataclass(frozen=True)
class ImportResolveResult:
    status: ImportOwnerStatus
    address: tuple[Address, ...] = ()


def _get_imports_info(
    address: Address,
    owners_per_import: Iterable[PythonModuleOwners],
    parsed_imports: ParsedPythonImports,
    explicitly_provided_deps: ExplicitlyProvidedDependencies,
) -> dict[str, ImportResolveResult]:
    def _resolve_single_import(owners, import_name) -> ImportResolveResult:
        if owners.unambiguous:
            return ImportResolveResult(ImportOwnerStatus.unambiguous, owners.unambiguous)

        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            owners.ambiguous,
            address,
            import_reference="module",
            context=f"The target {address} imports `{import_name}`",
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated(owners.ambiguous)
        if maybe_disambiguated:
            return ImportResolveResult(ImportOwnerStatus.disambiguated, (maybe_disambiguated,))
        elif import_name.split(".")[0] in DEFAULT_UNOWNED_DEPENDENCIES:
            return ImportResolveResult(ImportOwnerStatus.unownable)
        elif parsed_imports[import_name].weak:
            return ImportResolveResult(ImportOwnerStatus.weak_ignore)
        else:
            return ImportResolveResult(ImportOwnerStatus.unowned)

    return {
        imp: _resolve_single_import(owners, imp)
        for owners, (imp, inf) in zip(owners_per_import, parsed_imports.items())
    }


def _collect_imports_info(
    resolve_result: dict[str, ImportResolveResult]
) -> tuple[frozenset[Address], frozenset[str]]:
    """Collect import resolution results into:

    - imports (direct and disambiguated)
    - unowned
    """

    return frozenset(
        addr
        for dep in resolve_result.values()
        for addr in dep.address
        if (
            dep.status == ImportOwnerStatus.unambiguous
            or dep.status == ImportOwnerStatus.disambiguated
        )
    ), frozenset(
        imp for imp, dep in resolve_result.items() if dep.status == ImportOwnerStatus.unowned
    )


def _remove_ignored_imports(
    unowned_imports: frozenset[str], ignored_paths: tuple[str, ...]
) -> frozenset[str]:
    """Remove unowned imports given a list of paths to ignore.

    E.g. having
    ```
    import foo.bar
    from foo.bar import baz
    import foo.barley
    ```

    and passing `ignored-paths=["foo.bar"]`, only `foo.bar` and `foo.bar.baz` will be ignored.
    """
    if not ignored_paths:
        return unowned_imports

    unowned_imports_filtered = set()
    for unowned_import in unowned_imports:
        if not any(
            unowned_import == ignored_path or unowned_import.startswith(f"{ignored_path}.")
            for ignored_path in ignored_paths
        ):
            unowned_imports_filtered.add(unowned_import)
    return frozenset(unowned_imports_filtered)


@dataclass(frozen=True)
class UnownedImportsPossibleOwnersRequest:
    """A request to find possible owners for several imports originating in a resolve."""

    unowned_imports: frozenset[str]
    original_resolve: str


@dataclass(frozen=True)
class UnownedImportPossibleOwnerRequest:
    unowned_import: str
    original_resolve: str


@dataclass(frozen=True)
class UnownedImportsPossibleOwners:
    value: Dict[str, list[tuple[Address, ResolveName]]]


@dataclass(frozen=True)
class UnownedImportPossibleOwners:
    value: list[tuple[Address, ResolveName]]


async def _find_other_owners_for_unowned_imports(
    req: UnownedImportsPossibleOwnersRequest,
) -> UnownedImportsPossibleOwners:
    individual_possible_owners = await MultiGet(
        Get(UnownedImportPossibleOwners, UnownedImportPossibleOwnerRequest(r, req.original_resolve))
        for r in req.unowned_imports
    )

    return UnownedImportsPossibleOwners(
        {
            imported_module: possible_owners.value
            for imported_module, possible_owners in zip(
                req.unowned_imports, individual_possible_owners
            )
            if possible_owners.value
        }
    )


@rule
async def find_other_owners_for_unowned_import(
    req: UnownedImportPossibleOwnerRequest,
    python_setup: PythonSetup,
) -> UnownedImportPossibleOwners:
    other_owner_from_other_resolves = await Get(
        PythonModuleOwners,
        PythonModuleOwnersRequest(req.unowned_import, resolve=None, locality=None),
    )

    owners = other_owner_from_other_resolves
    other_owners_as_targets = await Get(Targets, Addresses(owners.unambiguous + owners.ambiguous))

    other_owners = []

    for t in other_owners_as_targets:
        other_owner_resolve = t[PythonResolveField].normalized_value(python_setup)
        if other_owner_resolve != req.original_resolve:
            other_owners.append((t.address, other_owner_resolve))
    return UnownedImportPossibleOwners(other_owners)


async def _handle_unowned_imports(
    address: Address,
    unowned_dependency_behavior: UnownedDependencyUsage,
    python_setup: PythonSetup,
    unowned_imports: frozenset[str],
    parsed_imports: ParsedPythonImports,
    resolve: str,
) -> None:
    if not unowned_imports or unowned_dependency_behavior is UnownedDependencyUsage.DoNothing:
        return

    other_resolves_snippet = ""
    if len(python_setup.resolves) > 1:
        imports_to_other_owners = (
            await _find_other_owners_for_unowned_imports(
                UnownedImportsPossibleOwnersRequest(unowned_imports, resolve),
            )
        ).value

        if imports_to_other_owners:
            other_resolves_lines = []
            for import_module, other_owners in sorted(imports_to_other_owners.items()):
                owners_txt = ", ".join(
                    f"'{other_resolve}' from {addr}" for addr, other_resolve in sorted(other_owners)
                )
                other_resolves_lines.append(f"{import_module}: {owners_txt}")
            other_resolves_snippet = "\n\n" + softwrap(
                f"""
                These imports are not in the resolve used by the target (`{resolve}`), but they
                were present in other resolves:

                {bullet_list(other_resolves_lines)}\n\n
                """
            )

    unowned_imports_with_lines = [
        f"{module_name} (line: {parsed_imports[module_name].lineno})"
        for module_name in sorted(unowned_imports)
    ]

    msg = softwrap(
        f"""
        Pants cannot infer owners for the following imports in the target {address}:

        {bullet_list(unowned_imports_with_lines)}{other_resolves_snippet}

        If you do not expect an import to be inferrable, add `# pants: no-infer-dep` to the
        import line. Otherwise, see
        {doc_url('docs/using-pants/troubleshooting-common-issues#import-errors-and-missing-dependencies')} for common problems.
        """
    )
    if unowned_dependency_behavior is UnownedDependencyUsage.LogWarning:
        logger.warning(msg)
    else:
        raise UnownedDependencyError(msg)


async def _exec_parse_deps(
    field_set: PythonImportDependenciesInferenceFieldSet,
    python_setup: PythonSetup,
) -> ParsedPythonDependencies:
    interpreter_constraints = InterpreterConstraints.create_from_compatibility_fields(
        [field_set.interpreter_constraints], python_setup
    )
    resp = await Get(
        ParsedPythonDependencies,
        ParsePythonDependenciesRequest(
            field_set.source,
            interpreter_constraints,
        ),
    )
    return resp


@dataclass(frozen=True)
class ResolvedParsedPythonDependenciesRequest:
    field_set: PythonImportDependenciesInferenceFieldSet
    parsed_dependencies: ParsedPythonDependencies
    resolve: Optional[str]


@dataclass(frozen=True)
class ResolvedParsedPythonDependencies:
    resolve_results: dict[str, ImportResolveResult]
    assets: dict[str, ImportResolveResult]
    explicit: ExplicitlyProvidedDependencies


@rule
async def resolve_parsed_dependencies(
    request: ResolvedParsedPythonDependenciesRequest,
    python_infer_subsystem: PythonInferSubsystem,
) -> ResolvedParsedPythonDependencies:
    """Find the owning targets for the parsed dependencies."""

    parsed_imports = request.parsed_dependencies.imports
    parsed_assets = request.parsed_dependencies.assets
    if not python_infer_subsystem.imports:
        parsed_imports = ParsedPythonImports([])

    explicitly_provided_deps = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)
    )

    # Only set locality if needed, to avoid unnecessary rule graph memoization misses.
    # When set, use the source root, which is useful in practice, but incurs fewer memoization
    # misses than using the full spec_path.
    locality = None
    if python_infer_subsystem.ambiguity_resolution == AmbiguityResolution.by_source_root:
        source_root = await Get(
            SourceRoot, SourceRootRequest, SourceRootRequest.for_address(request.field_set.address)
        )
        locality = source_root.path

    if parsed_imports:
        owners_per_import = await MultiGet(
            Get(
                PythonModuleOwners,
                PythonModuleOwnersRequest(imported_module, request.resolve, locality),
            )
            for imported_module in parsed_imports
        )
        resolve_results = _get_imports_info(
            address=request.field_set.address,
            owners_per_import=owners_per_import,
            parsed_imports=parsed_imports,
            explicitly_provided_deps=explicitly_provided_deps,
        )
    else:
        resolve_results = {}

    if parsed_assets:
        assets_by_path = await Get(AllAssetTargetsByPath)
        asset_deps = _get_inferred_asset_deps(
            request.field_set.address,
            request.field_set.source.file_path,
            assets_by_path,
            parsed_assets,
            explicitly_provided_deps,
        )
    else:
        asset_deps = {}

    return ResolvedParsedPythonDependencies(
        resolve_results=resolve_results,
        assets=asset_deps,
        explicit=explicitly_provided_deps,
    )


@rule(desc="Inferring Python dependencies by analyzing source")
async def infer_python_dependencies_via_source(
    request: InferPythonImportDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InferredDependencies:
    if not python_infer_subsystem.imports and not python_infer_subsystem.assets:
        return InferredDependencies([])

    parsed_dependencies = await _exec_parse_deps(request.field_set, python_setup)

    resolve = request.field_set.resolve.normalized_value(python_setup)

    resolved_dependencies = await Get(
        ResolvedParsedPythonDependencies,
        ResolvedParsedPythonDependenciesRequest(request.field_set, parsed_dependencies, resolve),
    )
    import_deps, unowned_imports = _collect_imports_info(resolved_dependencies.resolve_results)
    unowned_imports = _remove_ignored_imports(
        unowned_imports, python_infer_subsystem.ignored_unowned_imports
    )

    asset_deps, unowned_assets = _collect_imports_info(resolved_dependencies.assets)

    inferred_deps = import_deps | asset_deps

    await _handle_unowned_imports(
        request.field_set.address,
        python_infer_subsystem.unowned_dependency_behavior,
        python_setup,
        unowned_imports,
        parsed_dependencies.imports,
        resolve=resolve,
    )

    return InferredDependencies(sorted(inferred_deps))


@dataclass(frozen=True)
class InitDependenciesInferenceFieldSet(FieldSet):
    required_fields = (PythonSourceField, PythonResolveField)

    source: PythonSourceField
    resolve: PythonResolveField


class InferInitDependencies(InferDependenciesRequest):
    infer_from = InitDependenciesInferenceFieldSet


@rule(desc="Inferring dependencies on `__init__.py` files")
async def infer_python_init_dependencies(
    request: InferInitDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InferredDependencies:
    if python_infer_subsystem.init_files is InitFilesInference.never:
        return InferredDependencies([])

    ignore_empty_files = python_infer_subsystem.init_files is InitFilesInference.content_only
    fp = request.field_set.source.file_path
    assert fp is not None
    init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest(
            input_files=(fp,),
            requested=("__init__.py", "__init__.pyi"),
            ignore_empty_files=ignore_empty_files,
        ),
    )
    owners = await MultiGet(Get(Owners, OwnersRequest((f,))) for f in init_files.snapshot.files)

    owner_tgts = await Get(Targets, Addresses(itertools.chain.from_iterable(owners)))
    resolve = request.field_set.resolve.normalized_value(python_setup)
    python_owners = [
        tgt.address
        for tgt in owner_tgts
        if (
            tgt.has_field(PythonSourceField)
            and tgt[PythonResolveField].normalized_value(python_setup) == resolve
        )
    ]
    return InferredDependencies(python_owners)


@dataclass(frozen=True)
class ConftestDependenciesInferenceFieldSet(FieldSet):
    required_fields = (PythonTestSourceField, PythonResolveField)

    source: PythonTestSourceField
    resolve: PythonResolveField


class InferConftestDependencies(InferDependenciesRequest):
    infer_from = ConftestDependenciesInferenceFieldSet


@rule(desc="Inferring dependencies on `conftest.py` files")
async def infer_python_conftest_dependencies(
    request: InferConftestDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InferredDependencies:
    if not python_infer_subsystem.conftests:
        return InferredDependencies([])

    fp = request.field_set.source.file_path
    assert fp is not None
    conftest_files = await Get(
        AncestorFiles,
        AncestorFilesRequest(input_files=(fp,), requested=("conftest.py",)),
    )
    owners = await MultiGet(
        # NB: Because conftest.py files effectively always have content, we require an
        # owning target.
        Get(Owners, OwnersRequest((f,), owners_not_found_behavior=GlobMatchErrorBehavior.error))
        for f in conftest_files.snapshot.files
    )

    owner_tgts = await Get(Targets, Addresses(itertools.chain.from_iterable(owners)))
    resolve = request.field_set.resolve.normalized_value(python_setup)
    python_owners = [
        tgt.address
        for tgt in owner_tgts
        if (
            tgt.has_field(PythonSourceField)
            and tgt[PythonResolveField].normalized_value(python_setup) == resolve
        )
    ]
    return InferredDependencies(python_owners)


# This is a separate function to facilitate tests registering import inference.
def import_rules():
    return [
        resolve_parsed_dependencies,
        find_other_owners_for_unowned_import,
        infer_python_dependencies_via_source,
        *pex.rules(),
        *parse_python_dependencies.rules(),
        *module_mapper.rules(),
        *stripped_source_files.rules(),
        *target_types.rules(),
        *PythonInferSubsystem.rules(),
        *PythonSetup.rules(),
        UnionRule(InferDependenciesRequest, InferPythonImportDependencies),
    ]


def rules():
    return [
        *import_rules(),
        infer_python_init_dependencies,
        infer_python_conftest_dependencies,
        *ancestor_files.rules(),
        UnionRule(InferDependenciesRequest, InferInitDependencies),
        UnionRule(InferDependenciesRequest, InferConftestDependencies),
    ]
