# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from enum import Enum
from pathlib import PurePath
from typing import Dict, Iterable, Iterator, cast

from pants.backend.python.dependency_inference import module_mapper, parse_python_dependencies
from pants.backend.python.dependency_inference.default_unowned_dependencies import (
    DEFAULT_UNOWNED_DEPENDENCIES,
)
from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonAssets,
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
from pants.core.target_types import (
    AllAssetTargets,
    AllAssetTargetsRequest,
    FileSourceField,
    ResourceSourceField,
)
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
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import OwnersNotFoundBehavior
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
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

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--imports",
            default=True,
            type=bool,
            help=(
                "Infer a target's imported dependencies by parsing import statements from sources."
            ),
        )
        register(
            "--string-imports",
            default=False,
            type=bool,
            help=(
                "Infer a target's dependencies based on strings that look like dynamic "
                "dependencies, such as Django settings files expressing dependencies as strings. "
                "To ignore any false positives, put `!{bad_address}` in the `dependencies` field "
                "of your target."
            ),
        )
        register(
            "--string-imports-min-dots",
            default=2,
            type=int,
            help=(
                "If --string-imports is True, treat valid-looking strings with at least this many "
                "dots in them as potential dynamic dependencies. E.g., `'foo.bar.Baz'` will be "
                "treated as a potential dependency if this option is set to 2 but not if set to 3."
            ),
        )
        register(
            "--assets",
            default=False,
            type=bool,
            help=(
                "Infer a target's dependencies based on strings that look like Posix filepaths, "
                "such as those given to `open` or `pkgutil.get_data`. To ignore any false "
                "positives, put `!{bad_address}` in the `dependencies` field of your target."
            ),
        )
        register(
            "--asset-min-slashes",
            default=1,
            type=int,
            help=(
                "If --assets is True, treat valid-looking strings with at least this many forward "
                "slash characters as potential assets. E.g. `'data/databases/prod.db'` will be "
                "treated as a potential candidate if this option is set to 2 but not to 3."
            ),
        )
        register(
            "--inits",
            default=False,
            type=bool,
            help=(
                "Infer a target's dependencies on any `__init__.py` files in the packages "
                "it is located in (recursively upward in the directory structure).\n\nEven if this "
                "is disabled, Pants will still include any ancestor `__init__.py` files, only they "
                "will not be 'proper' dependencies, e.g. they will not show up in "
                "`./pants dependencies` and their own dependencies will not be used.\n\nIf you "
                "have empty `__init__.py` files, it's safe to leave this option off; otherwise, "
                "you should enable this option."
            ),
        )
        register(
            "--conftests",
            default=True,
            type=bool,
            help=(
                "Infer a test target's dependencies on any conftest.py files in the current "
                "directory and ancestor directories."
            ),
        )
        register(
            "--entry-points",
            default=True,
            type=bool,
            help=(
                "Infer dependencies on targets' entry points, e.g. `pex_binary`'s "
                "`entry_point` field, `python_awslambda`'s `handler` field and "
                "`python_distribution`'s `entry_points` field."
            ),
        )
        register(
            "--unowned-dependency-behavior",
            type=UnownedDependencyUsage,
            default=UnownedDependencyUsage.DoNothing,
            help=("How to handle inferred dependencies that don't have any owner."),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)

    @property
    def string_imports(self) -> bool:
        return cast(bool, self.options.string_imports)

    @property
    def string_imports_min_dots(self) -> int:
        return cast(int, self.options.string_imports_min_dots)

    @property
    def assets(self) -> bool:
        return cast(bool, self.options.assets)

    @property
    def asset_min_slashes(self) -> int:
        return cast(int, self.options.asset_min_slashes)

    @property
    def inits(self) -> bool:
        return cast(bool, self.options.inits)

    @property
    def conftests(self) -> bool:
        return cast(bool, self.options.conftests)

    @property
    def entry_points(self) -> bool:
        return cast(bool, self.options.entry_points)

    @property
    def unowned_dependency_behavior(self) -> UnownedDependencyUsage:
        return cast(UnownedDependencyUsage, self.options.unowned_dependency_behavior)


class InferPythonImportDependencies(InferDependenciesRequest):
    infer_from = PythonSourceField


def _get_inferred_resource_deps(
    all_asset_targets: AllAssetTargets,
    assets: ParsedPythonAssets,
) -> Iterator[Address]:
    assets_by_path: Dict[PurePath, Target] = {}
    for file_tgt in all_asset_targets.files:
        assets_by_path[PurePath(file_tgt[FileSourceField].file_path)] = file_tgt
    for resource_tgt in all_asset_targets.resources:
        path = PurePath(resource_tgt[ResourceSourceField].file_path)
        assets_by_path[path] = resource_tgt

    for pkgname, filepath in assets:
        resource_path = PurePath(*pkgname.split(".")).parent / filepath
        inferred_resource_tgt = assets_by_path.get(resource_path)
        if inferred_resource_tgt:
            yield inferred_resource_tgt.address


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
            asset_min_slashes=python_infer_subsystem.asset_min_slashes,
        ),
    )

    inferred_deps: set[Address] = set()
    unowned_imports: set[str] = set()
    parsed_imports = parsed_dependencies.imports
    parsed_assets = parsed_dependencies.assets
    if not python_infer_subsystem.imports:
        parsed_imports = ParsedPythonImports([])

    if parsed_imports:
        explicitly_provided_deps = await Get(
            ExplicitlyProvidedDependencies, DependenciesRequest(tgt[Dependencies])
        )
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
        inferred_deps.update(_get_inferred_resource_deps(all_asset_targets, parsed_assets))

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
