# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from enum import Enum
from pathlib import PurePath
from typing import DefaultDict, Iterable, Iterator, cast

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
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import Get, MultiGet, SubsystemRule, rule, rule_helper
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import OwnersNotFoundBehavior
from pants.option.option_types import BoolOption, EnumOption, IntOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name, doc_url
from pants.util.strutil import bullet_list, softwrap

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
        help=softwrap(
            """
            Infer a target's imported dependencies by parsing import statements from sources.

            To ignore a false positive, you can either put `# pants: no-infer-dep` on the line of
            the import or put `!{bad_address}` in the `dependencies` field of your target.
            """
        ),
    )
    string_imports = BoolOption(
        "--string-imports",
        default=False,
        help=softwrap(
            """
            Infer a target's dependencies based on strings that look like dynamic
            dependencies, such as Django settings files expressing dependencies as strings.

            To ignore any false positives, put `!{bad_address}` in the `dependencies` field
            of your target.
            """
        ),
    )
    string_imports_min_dots = IntOption(
        "--string-imports-min-dots",
        default=2,
        help=softwrap(
            """
            If --string-imports is True, treat valid-looking strings with at least this many
            dots in them as potential dynamic dependencies. E.g., `'foo.bar.Baz'` will be
            treated as a potential dependency if this option is set to 2 but not if set to 3.
            """
        ),
    )
    assets = BoolOption(
        "--assets",
        default=False,
        help=softwrap(
            """
            Infer a target's asset dependencies based on strings that look like Posix
            filepaths, such as those given to `open` or `pkgutil.get_data`. To ignore any
            false positives, put `!{bad_address}` in the `dependencies` field of your target.
            """
        ),
    )
    assets_min_slashes = IntOption(
        "--assets-min-slashes",
        default=1,
        help=softwrap(
            """
            If --assets is True, treat valid-looking strings with at least this many forward
            slash characters as potential assets. E.g. `'data/databases/prod.db'` will be
            treated as a potential candidate if this option is set to 2 but not to 3.
            """
        ),
    )
    inits = BoolOption(
        "--inits",
        default=False,
        help=softwrap(
            f"""
            Infer a target's dependencies on any `__init__.py` files in the packages
            it is located in (recursively upward in the directory structure).

            Even if this is disabled, Pants will still include any ancestor `__init__.py` files,
            only they will not be 'proper' dependencies, e.g. they will not show up in
            `{bin_name()} dependencies` and their own dependencies will not be used.

            If you have empty `__init__.py` files, it's safe to leave this option off; otherwise,
            you should enable this option.
            """
        ),
    )
    conftests = BoolOption(
        "--conftests",
        default=True,
        help=softwrap(
            """
            Infer a test target's dependencies on any conftest.py files in the current
            directory and ancestor directories.
            """
        ),
    )
    entry_points = BoolOption(
        "--entry-points",
        default=True,
        help=softwrap(
            """
            Infer dependencies on targets' entry points, e.g. `pex_binary`'s
            `entry_point` field, `python_awslambda`'s `handler` field and
            `python_distribution`'s `entry_points` field.
            """
        ),
    )
    unowned_dependency_behavior = EnumOption(
        "--unowned-dependency-behavior",
        default=UnownedDependencyUsage.DoNothing,
        help=softwrap(
            """
            How to handle imports that don't have an inferrable owner.

            Usually when an import cannot be inferred, it represents an issue like Pants not being
            properly configured, e.g. targets not set up. Often, missing dependencies will result
            in confusing runtime errors like `ModuleNotFoundError`, so this option can be helpful
            to error more eagerly.

            To ignore any false positives, either add `# pants: no-infer-dep` to the line of the
            import or put the import inside a `try: except ImportError:` block.
            """
        ),
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


@rule_helper
async def _handle_unowned_imports(
    address: Address,
    file: str,
    unowned_dependency_behavior: UnownedDependencyUsage,
    python_setup: PythonSetup,
    unowned_imports: Iterable[str],
    parsed_imports: ParsedPythonImports,
    resolve: str,
) -> None:
    if not unowned_imports or unowned_dependency_behavior is UnownedDependencyUsage.DoNothing:
        return

    other_resolves_snippet = ""
    if len(python_setup.resolves) > 1:
        other_owners_from_other_resolves = await MultiGet(
            Get(PythonModuleOwners, PythonModuleOwnersRequest(imported_module, resolve=None))
            for imported_module in unowned_imports
        )
        other_owners_as_targets = await MultiGet(
            Get(Targets, Addresses(owners.unambiguous + owners.ambiguous))
            for owners in other_owners_from_other_resolves
        )

        imports_to_other_owners: DefaultDict[str, list[tuple[Address, ResolveName]]] = defaultdict(
            list
        )
        for imported_module, targets in zip(unowned_imports, other_owners_as_targets):
            for t in targets:
                other_owner_resolve = t[PythonResolveField].normalized_value(python_setup)
                if other_owner_resolve != resolve:
                    imports_to_other_owners[imported_module].append(
                        (t.address, other_owner_resolve)
                    )

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
        {doc_url('troubleshooting#import-errors-and-missing-dependencies')} for common problems.
        """
    )
    if unowned_dependency_behavior is UnownedDependencyUsage.LogWarning:
        logger.warning(msg)
    else:
        raise UnownedDependencyError(msg)


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

    resolve = tgt[PythonResolveField].normalized_value(python_setup)

    if parsed_imports:
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

    _ = await _handle_unowned_imports(
        tgt.address,
        request.sources_field.file_path,
        python_infer_subsystem.unowned_dependency_behavior,
        python_setup,
        unowned_imports,
        parsed_imports,
        resolve=resolve,
    )

    return InferredDependencies(sorted(inferred_deps))


class InferInitDependencies(InferDependenciesRequest):
    infer_from = PythonSourceField


@rule(desc="Inferring dependencies on `__init__.py` files")
async def infer_python_init_dependencies(
    request: InferInitDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
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

    original_tgt, owner_tgts = await MultiGet(
        Get(WrappedTarget, Address, request.sources_field.address),
        Get(Targets, Addresses(itertools.chain.from_iterable(owners))),
    )
    resolve = original_tgt.target[PythonResolveField].normalized_value(python_setup)
    python_owners = [
        tgt.address
        for tgt in owner_tgts
        if (
            tgt.has_field(PythonSourceField)
            and tgt[PythonResolveField].normalized_value(python_setup) == resolve
        )
    ]
    return InferredDependencies(python_owners)


class InferConftestDependencies(InferDependenciesRequest):
    infer_from = PythonTestSourceField


@rule(desc="Inferring dependencies on `conftest.py` files")
async def infer_python_conftest_dependencies(
    request: InferConftestDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
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

    original_tgt, owner_tgts = await MultiGet(
        Get(WrappedTarget, Address, request.sources_field.address),
        Get(Targets, Addresses(itertools.chain.from_iterable(owners))),
    )
    resolve = original_tgt.target[PythonResolveField].normalized_value(python_setup)
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
