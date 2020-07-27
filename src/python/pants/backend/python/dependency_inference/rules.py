# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

from pants.backend.python.dependency_inference.import_parser import find_python_imports
from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwner
from pants.backend.python.dependency_inference.python_stdlib.combined import combined_stdlib
from pants.backend.python.rules.inject_ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.backend.python.target_types import PythonSources, PythonTestsSources
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSourcesFieldRequest,
)
from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.graph import Owners, OwnersNotFoundBehavior, OwnersRequest
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule


class InferPythonDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule(desc="Inferring Python dependencies.")
async def infer_python_dependencies(request: InferPythonDependencies) -> InferredDependencies:
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
async def infer_python_init_dependencies(request: InferInitDependencies) -> InferredDependencies:
    # Locate __init__.py files not already in the Snapshot.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    extra_init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("__init__.py", hydrated_sources.snapshot, sources_stripped=False),
    )

    # And add dependencies on their owners.
    return InferredDependencies(
        await Get(
            Owners, OwnersRequest(extra_init_files.snapshot.files, OwnersNotFoundBehavior.error)
        )
    )


class InferConftestDependencies(InferDependenciesRequest):
    infer_from = PythonTestsSources


@rule
async def infer_python_conftest_dependencies(
    request: InferConftestDependencies,
) -> InferredDependencies:
    # Locate conftest.py files not already in the Snapshot.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    extra_conftest_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("conftest.py", hydrated_sources.snapshot, sources_stripped=False),
    )

    # And add dependencies on their owners.
    return InferredDependencies(
        await Get(
            Owners, OwnersRequest(extra_conftest_files.snapshot.files, OwnersNotFoundBehavior.error)
        )
    )


def rules():
    return [
        infer_python_dependencies,
        infer_python_init_dependencies,
        infer_python_conftest_dependencies,
        UnionRule(InferDependenciesRequest, InferPythonDependencies),
        UnionRule(InferDependenciesRequest, InferInitDependencies),
        UnionRule(InferDependenciesRequest, InferConftestDependencies),
    ]
