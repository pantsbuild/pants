# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.rules.inject_init import InitInjectedSnapshot, InjectInitRequest
from pants.backend.python.rules.inject_init import rules as inject_init_rules
from pants.engine.fs import Snapshot
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.rules.core import determine_source_files
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles


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
    stripped_sources = await Get[SourceFiles](
        AllSourceFilesRequest((ht.adaptor for ht in hydrated_targets), strip_source_roots=True)
    )
    init_injected = await Get[InitInjectedSnapshot](InjectInitRequest(stripped_sources.snapshot))
    return ChrootedPythonSources(init_injected.snapshot)


def rules():
    return [prepare_chrooted_python_sources, *determine_source_files.rules(), *inject_init_rules()]
