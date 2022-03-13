# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from enum import Enum
from pathlib import PurePath
from typing import Iterable, Iterator, cast

from pants.backend.python.dependency_inference import module_mapper, parse_python_dependencies
from pants.backend.python.dependency_inference.default_unowned_dependencies import (
    DEFAULT_UNOWNED_DEPENDENCIES,
)
from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonAssetPaths,
    ParsedPythonDependencies,
    ParsedPythonImports,
    ParsePythonDependenciesRequest,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PythonResolveField,
    PythonSourceField,
    PythonTestSourceField,
)
from pants.backend.python.util_rules import ancestor_files, pex
from pants.backend.python.util_rules.ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core import target_types
from pants.core.target_types import AllAssetTargets, AllAssetTargetsByPath, AllAssetTargetsRequest
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import Get, MultiGet, SubsystemRule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import OwnersNotFoundBehavior
from pants.option.option_types import BoolOption, EnumOption, IntOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name, doc_url
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


class UnownedDependencyError(Exception):
    """The inferred dependency does not have any owner."""


class UnownedDependencyUsage(Enum):
    """What action to take when an inferred dependency is unowned."""

    RaiseError = "error"
    LogWarning = "warning"
    DoNothing = "ignore"


class PythonInferSubsystem(Subsystem):
    options_scope = "python-infer"
    help = "Options controlling which dependencies will be inferred for Python targets."

    imports = BoolOption(
        "--imports",
        default=True,
        help=("Infer a target's imported dependencies by parsing import statements from sources."),
    )
    string_imports = BoolOption(
        "--string-imports",
        default=False,
        help=(
            "Infer a target's dependencies based on strings that look like dynamic "
            "dependencies, such as Django settings files expressing dependencies as strings. "
            "To ignore any false positives, put `!{bad_address}` in the `dependencies` field "
            "of your target."
        ),
    )
    string_imports_min_dots = IntOption(
        "--string-imports-min-dots",
        default=2,
        help=(
            "If --string-imports is True, treat valid-looking strings with at least this many "
            "dots in them as potential dynamic dependencies. E.g., `'foo.bar.Baz'` will be "
            "treated as a potential dependency if this option is set to 2 but not if set to 3."
        ),
    )
    assets = BoolOption(
        "--assets",
        default=False,
        help=(
            "Infer a target's asset dependencies based on strings that look like Posix "
            "filepaths, such as those given to `open` or `pkgutil.get_data`. To ignore any "
            "false positives, put `!{bad_address}` in the `dependencies` field of your target."
        ),
    )
    assets_min_slashes = IntOption(
        "--assets-min-slashes",
        default=1,
        help=(
            "If --assets is True, treat valid-looking strings with at least this many forward "
            "slash characters as potential assets. E.g. `'data/databases/prod.db'` will be "
            "treated as a potential candidate if this option is set to 2 but not to 3."
        ),
    )
    inits = BoolOption(
        "--inits",
        default=False,
        help=(
            "Infer a target's dependencies on any `__init__.py` files in the packages "
            "it is located in (recursively upward in the directory structure).\n\nEven if this "
            "is disabled, Pants will still include any ancestor `__init__.py` files, only they "
            "will not be 'proper' dependencies, e.g. they will not show up in "
            f"`{bin_name()} dependencies` and their own dependencies will not be used.\n\nIf you "
            "have empty `__init__.py` files, it's safe to leave this option off; otherwise, "
            "you should enable this option."
        ),
    )
    conftests = BoolOption(
        "--conftests",
        default=True,
        help=(
            "Infer a test target's dependencies on any conftest.py files in the current "
            "directory and ancestor directories."
        ),
    )
    entry_points = BoolOption(
        "--entry-points",
        default=True,
        help=(
            "Infer dependencies on targets' entry points, e.g. `pex_binary`'s "
            "`entry_point` field, `python_awslambda`'s `handler` field and "
            "`python_distribution`'s `entry_points` field."
        ),
    )
    unowned_dependency_behavior = EnumOption(
        "--unowned-dependency-behavior",
        default=UnownedDependencyUsage.DoNothing,
        help=("How to handle inferred dependencies that don't have any owner."),
    )


class InferPythonImportDependencies(InferDependenciesRequest):
    infer_from = PythonSourceField


def _get_inferred_asset_deps(
    address: Address,
    request_file_path: str,
    assets_by_path: AllAssetTargetsByPath,
    assets: ParsedPythonAssetPaths,
    explicitly_provided_deps: ExplicitlyProvidedDependencies,
) -> Iterator[Address]:
    for filepath in assets:
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
            explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                possible_addresses,
                address,
                import_reference="asset",
                context=f"The target {address} uses `{filepath}`",
            )
            maybe_disambiguated = explicitly_provided_deps.disambiguated(possible_addresses)
            if maybe_disambiguated:
                yield maybe_disambiguated


def _get_imports_info(
    address: Address,
    owners_per_import: Iterable[PythonModuleOwners],
    parsed_imports: ParsedPythonImports,
    explicitly_provided_deps: ExplicitlyProvidedDependencies,
) -> tuple[set[Address], set[str]]:
    inferred_deps: set[Address] = set()
    unowned_imports: set[str] = set()

    for owners, imp in zip(owners_per_import, parsed_imports):
        inferred_deps.update(owners.unambiguous)
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            owners.ambiguous,
            address,
            import_reference="module",
            context=f"The target {address} imports `{imp}`",
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated(owners.ambiguous)
        if maybe_disambiguated:
            inferred_deps.add(maybe_disambiguated)

        if (
            not owners.unambiguous
            and imp.split(".")[0] not in DEFAULT_UNOWNED_DEPENDENCIES
            and not parsed_imports[imp].weak
        ):
            unowned_imports.add(imp)

    return inferred_deps, unowned_imports


def _maybe_warn_unowned(
    address: Address,
    file: str,
    unowned_dependency_behavior: UnownedDependencyUsage,
    unowned_imports: Iterable[str],
    parsed_imports: ParsedPythonImports,
) -> None:
    if unowned_imports and unowned_dependency_behavior is not UnownedDependencyUsage.DoNothing:
        unowned_imports_with_lines = [
            f"{module_name} ({file}:{parsed_imports[module_name].lineno})"
            for module_name in sorted(unowned_imports)
        ]
        raise_error = unowned_dependency_behavior is UnownedDependencyUsage.RaiseError
        log = logger.error if raise_error else logger.warning
        log(
            f"The following imports in {address} have no owners:\n\n{bullet_list(unowned_imports_with_lines)}\n\n"
            "If you are expecting this import to be provided by your own firstparty code, ensure that it is contained within a source root. "
            "Otherwise if you are using a requirements file, consider adding the relevant package.\n"
            "Otherwise consider declaring a `python_requirement_library` target, which can then be inferred.\n"
            f"See {doc_url('python-third-party-dependencies')}"
        )

        if raise_error:
            raise UnownedDependencyError(
                "One or more unowned dependencies detected. Check logs for more details."
            )


@rule(desc="Inferring Python dependencies by analyzing source")
async def infer_python_dependencies_via_source(
    request: InferPythonImportDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InferredDependencies:
    if not python_infer_subsystem.imports and not python_infer_subsystem.assets:
        return InferredDependencies([])

    _wrapped_tgt = await Get(WrappedTarget, Address, request.sources_field.address)
    tgt = _wrapped_tgt.target
    parsed_dependencies = await Get(
        ParsedPythonDependencies,
        ParsePythonDependenciesRequest(
            cast(PythonSourceField, request.sources_field),
            InterpreterConstraints.create_from_targets([tgt], python_setup),
            string_imports=python_infer_subsystem.string_imports,
            string_imports_min_dots=python_infer_subsystem.string_imports_min_dots,
            assets=python_infer_subsystem.assets,
            assets_min_slashes=python_infer_subsystem.assets_min_slashes,
        ),
    )

    inferred_deps: set[Address] = set()
    unowned_imports: set[str] = set()
    parsed_imports = parsed_dependencies.imports
    parsed_assets = parsed_dependencies.assets
    if not python_infer_subsystem.imports:
        parsed_imports = ParsedPythonImports([])

    explicitly_provided_deps = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(tgt[Dependencies])
    )

    if parsed_imports:
        resolve = tgt[PythonResolveField].normalized_value(python_setup)
        import_deps, unowned_imports = _get_imports_info(
            address=tgt.address,
            owners_per_import=await MultiGet(
                Get(PythonModuleOwners, PythonModuleOwnersRequest(imported_module, resolve=resolve))
                for imported_module in parsed_imports
            ),
            parsed_imports=parsed_imports,
            explicitly_provided_deps=explicitly_provided_deps,
        )
        inferred_deps.update(import_deps)

    if parsed_assets:
        all_asset_targets = await Get(AllAssetTargets, AllAssetTargetsRequest())
        assets_by_path = await Get(AllAssetTargetsByPath, AllAssetTargets, all_asset_targets)
        inferred_deps.update(
            _get_inferred_asset_deps(
                tgt.address,
                request.sources_field.file_path,
                assets_by_path,
                parsed_assets,
                explicitly_provided_deps,
            )
        )

    _maybe_warn_unowned(
        tgt.address,
        request.sources_field.file_path,
        python_infer_subsystem.unowned_dependency_behavior,
        unowned_imports,
        parsed_imports,
    )

    return InferredDependencies(sorted(inferred_deps))


class InferInitDependencies(InferDependenciesRequest):
    infer_from = PythonSourceField


@rule(desc="Inferring dependencies on `__init__.py` files")
async def infer_python_init_dependencies(
    request: InferInitDependencies, python_infer_subsystem: PythonInferSubsystem
) -> InferredDependencies:
    if not python_infer_subsystem.inits:
        return InferredDependencies([])

    fp = request.sources_field.file_path
    assert fp is not None
    init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest(input_files=(fp,), requested=("__init__.py", "__init__.pyi")),
    )
    owners = await MultiGet(Get(Owners, OwnersRequest((f,))) for f in init_files.snapshot.files)
    return InferredDependencies(itertools.chain.from_iterable(owners))


class InferConftestDependencies(InferDependenciesRequest):
    infer_from = PythonTestSourceField


@rule(desc="Inferring dependencies on `conftest.py` files")
async def infer_python_conftest_dependencies(
    request: InferConftestDependencies,
    python_infer_subsystem: PythonInferSubsystem,
) -> InferredDependencies:
    if not python_infer_subsystem.conftests:
        return InferredDependencies([])

    fp = request.sources_field.file_path
    assert fp is not None
    conftest_files = await Get(
        AncestorFiles,
        AncestorFilesRequest(input_files=(fp,), requested=("conftest.py",)),
    )
    owners = await MultiGet(
        # NB: Because conftest.py files effectively always have content, we require an
        # owning target.
        Get(Owners, OwnersRequest((f,), OwnersNotFoundBehavior.error))
        for f in conftest_files.snapshot.files
    )
    return InferredDependencies(itertools.chain.from_iterable(owners))


# This is a separate function to facilitate tests registering import inference.
def import_rules():
    return [
        infer_python_dependencies_via_source,
        *pex.rules(),
        *parse_python_dependencies.rules(),
        *module_mapper.rules(),
        *stripped_source_files.rules(),
        *target_types.rules(),
        SubsystemRule(PythonInferSubsystem),
        SubsystemRule(PythonSetup),
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
