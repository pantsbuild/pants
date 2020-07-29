# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from pathlib import PurePath
from typing import cast

from pants.backend.python.dependency_inference import module_mapper
from pants.backend.python.dependency_inference.import_parser import find_python_imports
from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwner
from pants.backend.python.dependency_inference.python_stdlib.combined import combined_stdlib
from pants.backend.python.rules import inject_ancestor_files
from pants.backend.python.rules.inject_ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.backend.python.target_types import PythonSources, PythonTestsSources
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSourcesFieldRequest,
)
from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import OwnersNotFoundBehavior
from pants.subsystem.subsystem import Subsystem


class PythonInference(Subsystem):
    """Options controlling which dependencies will be inferred for Python targets."""

    options_scope = "python-infer"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--imports",
            default=False,
            type=bool,
            help=(
                "Infer a target's imported dependencies by parsing import statements from sources."
            ),
        )
        register(
            "--inits",
            default=True,
            type=bool,
            help=(
                "Infer a target's dependencies on any __init__.py files existing for the packages "
                "it is located in (recursively upward in the directory structure)."
            ),
        )
        register(
            "--conftests",
            default=True,
            type=bool,
            help=(
                "Infer a test target's dependencies on any conftest.py files in parent directories."
            ),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)

    @property
    def inits(self) -> bool:
        return cast(bool, self.options.inits)

    @property
    def conftests(self) -> bool:
        return cast(bool, self.options.conftests)


class InferPythonDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule(desc="Inferring Python dependencies.")
async def infer_python_dependencies(
    request: InferPythonDependencies, python_inference: PythonInference
) -> InferredDependencies:
    if not python_inference.imports:
        return InferredDependencies()

    stripped_sources = await Get(
        SourceRootStrippedSources, StripSourcesFieldRequest(request.sources_field)
    )
    modules = tuple(
        PythonModule.create_from_stripped_path(PurePath(fp))
        for fp in stripped_sources.snapshot.files
    )
    digest_contents = await Get(DigestContents, Digest, stripped_sources.snapshot.digest)
    imports_per_file = tuple(
        find_python_imports(file_content.content.decode(), module_name=module.module)
        for file_content, module in zip(digest_contents, modules)
    )
    owner_per_import = await MultiGet(
        Get(PythonModuleOwner, PythonModule(imported_module))
        for file_imports in imports_per_file
        for imported_module in file_imports.explicit_imports
        if imported_module not in combined_stdlib
    )
    return InferredDependencies(
        owner.address
        for owner in owner_per_import
        if (
            owner.address
            and owner.address.maybe_convert_to_base_target() != request.sources_field.address
        )
    )


class InferInitDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule
async def infer_python_init_dependencies(
    request: InferInitDependencies, python_inference: PythonInference
) -> InferredDependencies:
    if not python_inference.inits:
        return InferredDependencies()

    # Locate __init__.py files not already in the Snapshot.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    extra_init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("__init__.py", hydrated_sources.snapshot, sources_stripped=False),
    )

    # And add dependencies on their owners.
    owners = await MultiGet(
        Get(Owners, OwnersRequest((f,), OwnersNotFoundBehavior.error))
        for f in extra_init_files.snapshot.files
    )
    return InferredDependencies(itertools.chain.from_iterable(owners))


class InferConftestDependencies(InferDependenciesRequest):
    infer_from = PythonTestsSources


@rule
async def infer_python_conftest_dependencies(
    request: InferConftestDependencies, python_inference: PythonInference,
) -> InferredDependencies:
    if not python_inference.conftests:
        return InferredDependencies()

    # Locate conftest.py files not already in the Snapshot.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    extra_conftest_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("conftest.py", hydrated_sources.snapshot, sources_stripped=False),
    )

    # And add dependencies on their owners.
    owners = await MultiGet(
        Get(Owners, OwnersRequest((f,), OwnersNotFoundBehavior.error))
        for f in extra_conftest_files.snapshot.files
    )
    return InferredDependencies(itertools.chain.from_iterable(owners))


def rules():
    return [
        *collect_rules(),
        *inject_ancestor_files.rules(),
        *module_mapper.rules(),
        UnionRule(InferDependenciesRequest, InferPythonDependencies),
        UnionRule(InferDependenciesRequest, InferInitDependencies),
        UnionRule(InferDependenciesRequest, InferConftestDependencies),
    ]
