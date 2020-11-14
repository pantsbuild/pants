# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from typing import List, cast

from pants.backend.python.dependency_inference import module_mapper
from pants.backend.python.dependency_inference.import_parser import find_python_imports
from pants.backend.python.dependency_inference.module_mapper import PythonModule, PythonModuleOwners
from pants.backend.python.dependency_inference.python_stdlib.combined import combined_stdlib
from pants.backend.python.target_types import PythonSources, PythonTestsSources
from pants.backend.python.util_rules import ancestor_files
from pants.backend.python.util_rules.ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
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
from pants.option.subsystem import Subsystem


class PythonInference(Subsystem):
    """Options controlling which dependencies will be inferred for Python targets."""

    options_scope = "python-infer"

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
                "it is located in (recursively upward in the directory structure). Even if this is "
                "disabled, Pants will still include any ancestor __init__.py files, only they will "
                "not be 'proper' dependencies, e.g. they will not show up in "
                "`./pants dependencies` and their own dependencies will not be used. If you have "
                "empty `__init__.py` files, it's safe to leave this option off; otherwise, you "
                "should enable this option."
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


class InferPythonDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule(desc="Inferring Python dependencies.")
async def infer_python_dependencies(
    request: InferPythonDependencies, python_inference: PythonInference
) -> InferredDependencies:
    if not python_inference.imports:
        return InferredDependencies([], sibling_dependencies_inferrable=False)

    stripped_sources = await Get(StrippedSourceFiles, SourceFilesRequest([request.sources_field]))
    digest_contents = await Get(DigestContents, Digest, stripped_sources.snapshot.digest)

    owners_requests: List[Get[PythonModuleOwners, PythonModule]] = []
    for file_content in digest_contents:
        file_imports_obj = find_python_imports(
            filename=file_content.path,
            content=file_content.content.decode(),
        )
        detected_imports = (
            file_imports_obj.all_imports
            if python_inference.string_imports
            else file_imports_obj.explicit_imports
        )
        owners_requests.extend(
            Get(PythonModuleOwners, PythonModule(imported_module))
            for imported_module in detected_imports
            if imported_module not in combined_stdlib
        )

    owners_per_import = await MultiGet(owners_requests)
    # We remove the request's address so that we don't infer dependencies on self.
    merged_result = sorted(
        set(itertools.chain.from_iterable(owners_per_import)) - {request.sources_field.address}
    )
    return InferredDependencies(merged_result, sibling_dependencies_inferrable=True)


class InferInitDependencies(InferDependenciesRequest):
    infer_from = PythonSources


@rule(desc="Inferring dependencies on `__init__.py` files")
async def infer_python_init_dependencies(
    request: InferInitDependencies, python_inference: PythonInference
) -> InferredDependencies:
    if not python_inference.inits:
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
    python_inference: PythonInference,
) -> InferredDependencies:
    if not python_inference.conftests:
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


def rules():
    return [
        *collect_rules(),
        *ancestor_files.rules(),
        *module_mapper.rules(),
        UnionRule(InferDependenciesRequest, InferPythonDependencies),
        UnionRule(InferDependenciesRequest, InferInitDependencies),
        UnionRule(InferDependenciesRequest, InferConftestDependencies),
    ]
