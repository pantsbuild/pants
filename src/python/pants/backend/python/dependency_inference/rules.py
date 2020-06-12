# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

from pants.backend.python.dependency_inference.import_parser import find_python_imports
from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwner
from pants.backend.python.dependency_inference.python_stdlib.combined import combined_stdlib
from pants.backend.python.target_types import PythonSources
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSourcesFieldRequest,
)
from pants.engine.fs import Digest, FilesContent
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule


class InferPythonDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule
async def infer_python_dependencies(request: InferPythonDependencies) -> InferredDependencies:
    stripped_sources = await Get[SourceRootStrippedSources](
        StripSourcesFieldRequest(request.sources_field)
    )
    modules = tuple(
        PythonModule.create_from_stripped_path(PurePath(fp))
        for fp in stripped_sources.snapshot.files
    )
    files_content = await Get[FilesContent](Digest, stripped_sources.snapshot.digest)
    imports_per_file = tuple(
        find_python_imports(fc.content.decode(), module_name=module.module)
        for fc, module in zip(files_content, modules)
    )
    owner_per_import = await MultiGet(
        Get[PythonModuleOwner](PythonModule(imported_module))
        for file_imports in imports_per_file
        for imported_module in file_imports.all_imports
        if imported_module not in combined_stdlib
    )
    return InferredDependencies(
        owner.address
        for owner in owner_per_import
        if owner.address and owner.address != request.sources_field.address
    )


def rules():
    return [infer_python_dependencies, UnionRule(InferDependenciesRequest, InferPythonDependencies)]
