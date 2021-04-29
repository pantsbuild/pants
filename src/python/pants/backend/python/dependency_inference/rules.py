# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from typing import cast

from pants.backend.python.dependency_inference import import_parser, module_mapper
from pants.backend.python.dependency_inference.import_parser import (
    ParsedPythonImports,
    ParsePythonImportsRequest,
)
from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.dependency_inference.python_stdlib.combined import combined_stdlib
from pants.backend.python.target_types import PythonSources, PythonTestsSources
from pants.backend.python.util_rules import ancestor_files, pex
from pants.backend.python.util_rules.ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.backend.python.util_rules.pex import PexInterpreterConstraints
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import Get, MultiGet, SubsystemRule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import OwnersNotFoundBehavior
from pants.option.subsystem import Subsystem
from pants.python.python_setup import PythonSetup

logger = logging.getLogger(__name__)


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
            "--inits",
            default=False,
            type=bool,
            help=(
                "Infer a target's dependencies on any __init__.py files existing for the packages "
                "it is located in (recursively upward in the directory structure).\n\nEven if this "
                "is disabled, Pants will still include any ancestor __init__.py files, only they "
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
                "Infer dependencies on binary targets' entry points, e.g. `pex_binary`'s "
                "`entry_point` field and `python_awslambda`'s `handler` field."
            ),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)

    @property
    def string_imports(self) -> bool:
        return cast(bool, self.options.string_imports)

    @property
    def inits(self) -> bool:
        return cast(bool, self.options.inits)

    @property
    def conftests(self) -> bool:
        return cast(bool, self.options.conftests)

    @property
    def entry_points(self) -> bool:
        return cast(bool, self.options.entry_points)


class InferPythonImportDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule(desc="Inferring Python dependencies by analyzing imports")
async def infer_python_dependencies_via_imports(
    request: InferPythonImportDependencies,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> InferredDependencies:
    if not python_infer_subsystem.imports:
        return InferredDependencies([], sibling_dependencies_inferrable=False)

    wrapped_tgt = await Get(WrappedTarget, Address, request.sources_field.address)
    explicitly_provided_deps, detected_imports = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(
            ParsedPythonImports,
            ParsePythonImportsRequest(
                request.sources_field,
                PexInterpreterConstraints.create_from_targets([wrapped_tgt.target], python_setup),
                string_imports=python_infer_subsystem.string_imports,
            ),
        ),
    )
    relevant_imports = detected_imports - combined_stdlib

    owners_per_import = await MultiGet(
        Get(PythonModuleOwners, PythonModule(imported_module))
        for imported_module in relevant_imports
    )
    merged_result: set[Address] = set()
    for owners, imp in zip(owners_per_import, relevant_imports):
        merged_result.update(owners.unambiguous)
        address = wrapped_tgt.target.address
        explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
            owners.ambiguous,
            address,
            import_reference="module",
            context=f"The target {address} imports `{imp}`",
        )
        maybe_disambiguated = explicitly_provided_deps.disambiguated_via_ignores(owners.ambiguous)
        if maybe_disambiguated:
            merged_result.add(maybe_disambiguated)

    return InferredDependencies(sorted(merged_result), sibling_dependencies_inferrable=True)


class InferInitDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule(desc="Inferring dependencies on `__init__.py` files")
async def infer_python_init_dependencies(
    request: InferInitDependencies, python_infer_subsystem: PythonInferSubsystem
) -> InferredDependencies:
    if not python_infer_subsystem.inits:
        return InferredDependencies([], sibling_dependencies_inferrable=False)

    # Locate __init__.py files not already in the Snapshot.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    extra_init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("__init__.py", hydrated_sources.snapshot),
    )

    # And add dependencies on their owners.
    # NB: Because the python_sources rules always locate __init__.py files, and will trigger an
    # error for files that have content but have not already been included via a dependency, we
    # don't need to error for unowned files here.
    owners = await MultiGet(
        Get(Owners, OwnersRequest((f,))) for f in extra_init_files.snapshot.files
    )
    return InferredDependencies(
        itertools.chain.from_iterable(owners), sibling_dependencies_inferrable=False
    )


class InferConftestDependencies(InferDependenciesRequest):
    infer_from = PythonTestsSources


@rule(desc="Inferring dependencies on `conftest.py` files")
async def infer_python_conftest_dependencies(
    request: InferConftestDependencies,
    python_infer_subsystem: PythonInferSubsystem,
) -> InferredDependencies:
    if not python_infer_subsystem.conftests:
        return InferredDependencies([], sibling_dependencies_inferrable=False)

    # Locate conftest.py files not already in the Snapshot.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    extra_conftest_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("conftest.py", hydrated_sources.snapshot),
    )

    # And add dependencies on their owners.
    # NB: Because conftest.py files effectively always have content, we require an owning target.
    owners = await MultiGet(
        Get(Owners, OwnersRequest((f,), OwnersNotFoundBehavior.error))
        for f in extra_conftest_files.snapshot.files
    )
    return InferredDependencies(
        itertools.chain.from_iterable(owners), sibling_dependencies_inferrable=False
    )


# This is a separate function to facilitate tests registering import inference.
def import_rules():
    return [
        infer_python_dependencies_via_imports,
        *pex.rules(),
        *import_parser.rules(),
        *module_mapper.rules(),
        *stripped_source_files.rules(),
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
