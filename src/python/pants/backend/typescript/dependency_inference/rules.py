# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from pants.backend.javascript.dependency_inference.rules import _prepare_inference_metadata
from pants.backend.typescript.target_types import (
    TS_FILE_EXTENSIONS,
    TSDependenciesField,
    TSGeneratorSourcesField,
    TSSourceField,
    TSTestDependenciesField,
    TSTestsGeneratorSourcesField,
    TSTestSourceField,
)
from pants.build_graph.address import Address, ResolveError
from pants.engine.addresses import Addresses
from pants.engine.internals.native_dep_inference import NativeParsedJavascriptDependencies
from pants.engine.internals.native_engine import NativeDependenciesRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    FieldSet,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


class TypeScriptSourceNotFound(Exception):
    pass


@dataclass(frozen=True)
class TypeScriptTestDependencyInferenceFieldSet(FieldSet):
    """Target typescript_test."""

    required_fields = (TSTestSourceField, TSTestDependenciesField)

    source: TSTestSourceField
    dependencies: TSTestDependenciesField


class InferDepsTypeScriptTestDependenciesRequest(InferDependenciesRequest):
    """Target generator typescript_tests."""

    infer_from = TypeScriptTestDependencyInferenceFieldSet


@dataclass(frozen=True)
class TypeScriptTestsDependencyInferenceFieldSet(FieldSet):
    """Target generator typescript_tests."""

    required_fields = (TSTestsGeneratorSourcesField, TSTestDependenciesField)

    sources: TSGeneratorSourcesField
    dependencies: TSTestDependenciesField


class InferDepsTypeScriptTestsDependenciesRequest(InferDependenciesRequest):
    """Target generator typescript_tests."""

    infer_from = TypeScriptTestsDependencyInferenceFieldSet


@dataclass(frozen=True)
class TypeScriptSourcesDependencyInferenceFieldSet(FieldSet):
    """Target generator typescript_sources."""

    required_fields = (TSGeneratorSourcesField, TSDependenciesField)

    sources: TSGeneratorSourcesField
    dependencies: TSDependenciesField


class InferDepsTypeScriptSourcesDependenciesRequest(InferDependenciesRequest):
    """Target generator typescript_sources."""

    infer_from = TypeScriptSourcesDependencyInferenceFieldSet


@dataclass(frozen=True)
class TypeScriptSourceDependencyInferenceFieldSet(FieldSet):
    """Target typescript_source."""

    required_fields = (TSSourceField, TSDependenciesField)

    source: TSSourceField
    dependencies: TSDependenciesField


class InferDepsTypeScriptSourceDependenciesRequest(InferDependenciesRequest):
    """Target typescript_source."""

    infer_from = TypeScriptSourceDependencyInferenceFieldSet


@dataclass(frozen=True)
class TypeScriptTestTargetFilepath:
    filepath: str


@dataclass(frozen=True)
class InferredTypeScriptDependencies:
    addresses: list[Address]


@dataclass(frozen=True)
class RequestWrapper:
    request: Union[
        InferDepsTypeScriptTestDependenciesRequest,
        InferDepsTypeScriptTestsDependenciesRequest,
        InferDepsTypeScriptSourcesDependenciesRequest,
        InferDepsTypeScriptSourceDependenciesRequest,
    ]


def raise_dep_infer_failure(address: Address, path: str):
    raise ValueError(
        f"Failed to infer dependencies for target `{address}`.\n"
        f"Could not process process inferred dependency on `{path}` expecting `{address}` to be present."
    )


@rule("Generic rule to infer dependencies of TypeScript targets.")
async def infer_typescript_dependencies(
    request_wrapper: RequestWrapper,
) -> InferredTypeScriptDependencies:
    """Infer dependencies for TypeScript targets."""
    # depending on whether it's a target or target generator, get an appropriate field from the field set
    # TODO: there must be a better way?
    if hasattr(request_wrapper.request.field_set, "source"):
        sources = await Get(
            HydratedSources, HydrateSourcesRequest(request_wrapper.request.field_set.source)
        )
    else:
        sources = await Get(
            HydratedSources, HydrateSourcesRequest(request_wrapper.request.field_set.sources)
        )

    # TODO: we need to fetch all relevant tsconfig.json files that may contain the path mappings;
    #  see https://www.typescriptlang.org/tsconfig#paths to learn more.
    #  We also need jest.config.ts files for tests (and more config files as we add support for other test runners);
    #  see https://jestjs.io/docs/configuration to learn more.
    #  e.g. something like this:
    # path_mapping_digest = await Get(Digest, PathGlobs(["**/*/tsconfig*.json"]))
    # path_mapping_contents_result = await Get(DigestContents, Digest, path_mapping_digest)
    # path_mapping = json.loads(path_mapping_contents_result[0].content.decode("utf-8"))
    # logger.warning(path_mapping["compilerOptions"]["paths"])
    # TODO: use the mapping to map the import paths

    metadata = await _prepare_inference_metadata(request_wrapper.request.field_set.address)
    import_strings = await Get(
        NativeParsedJavascriptDependencies,
        NativeDependenciesRequest(sources.snapshot.digest, metadata),
    )
    logger.warning((sources.snapshot.files[0], import_strings))

    addresses = []

    for path in import_strings.file_imports:
        # check if an import is a directory (that should contain `index.ts` or `index.tsx`)
        if Path(path).is_dir():
            address = None
            for ext in TS_FILE_EXTENSIONS:
                try:
                    address = Address(path, relative_file_path=f"index{ext}")
                    _ = await Get(Targets, Addresses([address]))
                    addresses.append(address)
                    break
                except ResolveError:
                    pass

            if not address:
                raise_dep_infer_failure(
                    address=request_wrapper.request.field_set.address, path=path
                )

        else:
            # trying to find a file on disk using multiple extensions
            package, filename = os.path.dirname(path), os.path.basename(path)
            address = None
            for ext in TS_FILE_EXTENSIONS:
                try:
                    address = Address(package, relative_file_path=f"{filename}{ext}")
                    _ = await Get(Targets, Addresses([address]))
                    addresses.append(address)
                    break
                except ResolveError:
                    pass

            if not address:
                raise_dep_infer_failure(
                    address=request_wrapper.request.field_set.address, path=path
                )

    # analyze package imports
    for package in import_strings.package_imports:
        if package.startswith("@"):
            # it's a 3rd-party package?
            continue

        # importing a member from `index.ts` from a package in the root directory
        # having `import { foo } from 'bar';` means there may be
        # `src/bar/index.ts` if `bar` is a first-party code package
        for ext in TS_FILE_EXTENSIONS:
            # TODO: the import statements are not providing absolute paths; we have to figure out somehow what address
            #  this import points to; it's easy when you know where all the TypeScript sources are declared, but how
            #  does one do that without having this piece of information?
            root_dir = "frontend"
            try:
                if Path(os.path.join(root_dir, package)).is_dir():
                    address = Address(
                        os.path.join(root_dir, package),
                        relative_file_path=f"index{ext}",
                    )
                else:
                    package_name, filename = os.path.dirname(package), os.path.basename(package)
                    address = Address(
                        os.path.join(root_dir, package_name),
                        relative_file_path=f"{filename}{ext}",
                    )
                _ = await Get(Targets, Addresses([address]))
                addresses.append(address)
                break
            except ResolveError:
                # it's okay if there's no directory in the root directory; it could be a 3rd-party package,
                # e.g. `import { type foo, type bar } from 'redux';`
                pass

    return InferredTypeScriptDependencies(addresses)


@rule("Get dependencies of typescript_test targets.")
async def get_dependencies_typescript_test(
    request: InferDepsTypeScriptTestDependenciesRequest,
) -> InferredDependencies:
    """Get dependencies for individual `typescript_test` targets."""
    result = await Get(InferredTypeScriptDependencies, RequestWrapper, RequestWrapper(request))
    return InferredDependencies(result.addresses)


@rule("Get dependencies of typescript_tests targets.")
async def get_dependencies_typescript_tests(
    request: InferDepsTypeScriptTestsDependenciesRequest,
) -> InferredDependencies:
    """Get dependencies for all `typescript_test` targets when running the peek goal on a target
    generator."""
    result = await Get(InferredTypeScriptDependencies, RequestWrapper, RequestWrapper(request))
    return InferredDependencies(result.addresses)


@rule("Get dependencies of typescript_sources targets.")
async def get_dependencies_typescript_sources(
    request: InferDepsTypeScriptSourcesDependenciesRequest,
) -> InferredDependencies:
    """Get dependencies for `typescript_sources` target generator."""
    result = await Get(InferredTypeScriptDependencies, RequestWrapper, RequestWrapper(request))
    return InferredDependencies(result.addresses)


@rule("Get dependencies of typescript_source targets.")
async def get_dependencies_typescript_source(
    request: InferDepsTypeScriptSourceDependenciesRequest,
) -> InferredDependencies:
    """Get dependencies for individual `typescript_source` targets."""
    result = await Get(InferredTypeScriptDependencies, RequestWrapper, RequestWrapper(request))
    return InferredDependencies(result.addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferDepsTypeScriptTestDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferDepsTypeScriptTestsDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferDepsTypeScriptSourceDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferDepsTypeScriptSourcesDependenciesRequest),
    )
