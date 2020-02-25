# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.rules.inject_init import InitInjectedSnapshot, InjectInitRequest
from pants.backend.python.rules.inject_init import rules as inject_init_rules
from pants.engine.fs import DirectoriesToMerge, Snapshot
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripTargetRequest


@dataclass(frozen=True)
class ChrootedPythonSources:
    snapshot: Snapshot


@rule
async def prepare_chrooted_python_sources(
    hydrated_targets: HydratedTargets,
) -> ChrootedPythonSources:
    """Prepares Python sources by stripping the source root and injecting missing __init__.py files.

    NB: This is useful for Pytest or ./pants run, but not every Python rule will need this.
    For example, autoformatters like Black do not need to understand relative imports or
    execute the code, so they can safely operate on the original source files without
    stripping source roots.
    """
    source_root_stripped_sources = await MultiGet(
        Get[SourceRootStrippedSources](StripTargetRequest(hydrated_target.adaptor))
        for hydrated_target in hydrated_targets
    )
    sources_snapshot = await Get[Snapshot](
        DirectoriesToMerge(
            directories=tuple(
                stripped_sources.snapshot.directory_digest
                for stripped_sources in source_root_stripped_sources
            )
        )
    )
    result = await Get[InitInjectedSnapshot](InjectInitRequest(sources_snapshot))
    return ChrootedPythonSources(result.snapshot)


def rules():
    return [prepare_chrooted_python_sources, *inject_init_rules()]
