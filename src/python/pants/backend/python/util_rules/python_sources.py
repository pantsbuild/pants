# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, List, Tuple, Type

from pants.backend.python.target_types import PythonSources
from pants.backend.python.util_rules import ancestor_files
from pants.backend.python.util_rules.ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules import source_files, stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import MergeDigests, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest, Sources, Target
from pants.engine.unions import UnionMembership
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class PythonSourceFiles:
    """Sources that can be introspected by Python, relative to a set of source roots.

    Specifically, this will filter out to only have Python, and, optionally, resources() and
    files() targets; and will add any missing `__init__.py` files to ensure that modules are
    recognized correctly.

    Use-cases that introspect Python source code (e.g., the `test, `lint`, `fmt` goals) can
    request this type to get relevant sources that are still relative to their source roots.
    That way the paths they report are the unstripped ones the user is familiar with.

    The sources can also be imported and used by Python (e.g., for the `test` goal), but only
    if sys.path is modified to include the source roots.
    """

    source_files: SourceFiles
    source_roots: Tuple[str, ...]  # Source roots for the specified source files.


@dataclass(frozen=True)
class StrippedPythonSourceFiles:
    """A PythonSourceFiles that has had its source roots stripped."""

    stripped_source_files: StrippedSourceFiles


@frozen_after_init
@dataclass(unsafe_hash=True)
class PythonSourceFilesRequest:
    targets: Tuple[Target, ...]
    include_resources: bool
    include_files: bool

    def __init__(
        self,
        targets: Iterable[Target],
        *,
        include_resources: bool = True,
        include_files: bool = False
    ) -> None:
        self.targets = tuple(targets)
        self.include_resources = include_resources
        self.include_files = include_files

    @property
    def valid_sources_types(self) -> Tuple[Type[Sources], ...]:
        types: List[Type[Sources]] = [PythonSources]
        if self.include_resources:
            types.append(ResourcesSources)
        if self.include_files:
            types.append(FilesSources)
        return tuple(types)


@rule(level=LogLevel.DEBUG)
async def prepare_python_sources(
    request: PythonSourceFilesRequest, union_membership: UnionMembership
) -> PythonSourceFiles:
    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            (tgt.get(Sources) for tgt in request.targets),
            for_sources_types=request.valid_sources_types,
            enable_codegen=True,
        ),
    )

    missing_init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("__init__.py", sources.snapshot),
    )

    init_injected = await Get(
        Snapshot,
        MergeDigests((sources.snapshot.digest, missing_init_files.snapshot.digest)),
    )

    # Codegen is able to generate code in any arbitrary location, unlike sources normally being
    # rooted under the target definition. To determine source roots for these generated files, we
    # cannot use the normal `SourceRootRequest.for_target()` and we instead must determine
    # a source root for every individual generated file. So, we re-resolve the codegen sources here.
    python_and_resources_targets = []
    codegen_targets = []
    for tgt in request.targets:
        if tgt.has_field(PythonSources) or tgt.has_field(ResourcesSources):
            python_and_resources_targets.append(tgt)
        elif tgt.get(Sources).can_generate(PythonSources, union_membership) or tgt.get(
            Sources
        ).can_generate(ResourcesSources, union_membership):
            codegen_targets.append(tgt)
    codegen_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt.get(Sources), for_sources_types=request.valid_sources_types, enable_codegen=True
            ),
        )
        for tgt in codegen_targets
    )
    source_root_requests = [
        *(SourceRootRequest.for_target(tgt) for tgt in python_and_resources_targets),
        *(
            SourceRootRequest.for_file(f)
            for sources in codegen_sources
            for f in sources.snapshot.files
        ),
    ]

    source_root_objs = await MultiGet(
        Get(SourceRoot, SourceRootRequest, req) for req in source_root_requests
    )
    source_root_paths = {source_root_obj.path for source_root_obj in source_root_objs}
    return PythonSourceFiles(
        SourceFiles(init_injected, sources.unrooted_files), tuple(sorted(source_root_paths))
    )


@rule(level=LogLevel.DEBUG)
async def strip_python_sources(python_sources: PythonSourceFiles) -> StrippedPythonSourceFiles:
    stripped = await Get(StrippedSourceFiles, SourceFiles, python_sources.source_files)
    return StrippedPythonSourceFiles(stripped)


def rules():
    return [
        *collect_rules(),
        *ancestor_files.rules(),
        *source_files.rules(),
        *stripped_source_files.rules(),
    ]
