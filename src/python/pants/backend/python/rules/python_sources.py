# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.rules.inject_init import InitInjectedSnapshot, InjectInitRequest
from pants.backend.python.rules.inject_init import rules as inject_init_rules
from pants.backend.python.target_types import PythonSources
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules import determine_source_files
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.core.util_rules.strip_source_roots import representative_path_from_address
from pants.engine.fs import Snapshot
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Sources, Targets
from pants.source.source_root import SourceRoot, SourceRootRequest


@dataclass(frozen=True)
class StrippedPythonSources:
    """Sources that can be imported and used by Python, relative to the root.

    Specifically, this will filter out to only have Python, resources(), and files() targets;
    strip source roots, e.g. `src/python/f.py` -> `f.py`; and will add any missing
    `__init__.py` files to ensure that modules are recognized correctly.

    Use-cases that execute the Python source code (e.g., the `run`, `binary` and `repl` goals) can
    request this type to get a single tree of relevant sources that can be run without sys.path
    manipulation.
    """

    snapshot: Snapshot


@dataclass(frozen=True)
class UnstrippedPythonSources:
    """Sources that can be introspected by Python, relative to a set of source roots.

    Specifically, this will filter out to only have Python, resources(), and files() targets;
    and will add any missing `__init__.py` files to ensure that modules are recognized correctly.

    Use-cases that introspect Python source code (e.g., the `test, `lint`, `fmt` goals) can
    request this type to get relevant sources that are still relative to their source roots.
    That way the paths they report are the unstripped ones the user is familiar with.

    The sources can also be imported and used by Python (e.g., for the `test` goal), but only
    if sys.path is modified to include the source roots.
    """

    snapshot: Snapshot
    source_roots: Tuple[str, ...]


@rule
async def prepare_stripped_python_sources(targets: Targets) -> StrippedPythonSources:
    stripped_sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in targets),
            for_sources_types=(PythonSources, ResourcesSources, FilesSources),
            enable_codegen=True,
            strip_source_roots=True,
        )
    )
    init_injected = await Get[InitInjectedSnapshot](
        InjectInitRequest(sources_snapshot=stripped_sources.snapshot, sources_stripped=True)
    )
    return StrippedPythonSources(init_injected.snapshot)


@rule
async def prepare_unstripped_python_sources(targets: Targets) -> UnstrippedPythonSources:
    sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in targets),
            for_sources_types=(PythonSources, ResourcesSources, FilesSources),
            enable_codegen=True,
            strip_source_roots=False,
        )
    )

    source_root_objs = await MultiGet(
        Get[SourceRoot](
            SourceRootRequest,
            SourceRootRequest.for_file(representative_path_from_address(tgt.address)),
        )
        for tgt in targets
        if tgt.has_field(PythonSources) or tgt.has_field(ResourcesSources)
    )
    source_root_paths = {source_root_obj.path for source_root_obj in source_root_objs}

    init_injected = await Get[InitInjectedSnapshot](
        InjectInitRequest(sources.snapshot, sources_stripped=False)
    )
    return UnstrippedPythonSources(init_injected.snapshot, tuple(sorted(source_root_paths)))


def rules():
    return [
        prepare_stripped_python_sources,
        prepare_unstripped_python_sources,
        *determine_source_files.rules(),
        *inject_init_rules(),
        RootRule(Targets),
    ]
