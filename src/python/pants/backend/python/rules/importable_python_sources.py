# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.rules.inject_init import InitInjectedSnapshot, InjectInitRequest
from pants.backend.python.rules.inject_init import rules as inject_init_rules
from pants.backend.python.target_types import PythonSources
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules import determine_source_files
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.engine.fs import Snapshot
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.engine.target import Sources, Targets


@dataclass(frozen=True)
class ImportablePythonSources:
    """Sources that can be imported and used by Python, e.g. with tools like Pytest or with `./pants
    run`.

    Specifically, this will filter out to only have Python, resources(), and files() targets; will
    strip source roots, e.g. `src/python/f.py` -> `f.py`; and will add any missing
    `__init__.py` files to ensure that modules are recognized correctly.

    Not every Python application will need to request this type. For example, autoformatters like
    Black never need to actually import and run the Python code, so they do not need to use this.
    """

    snapshot: Snapshot


@rule
async def prepare_python_sources(targets: Targets) -> ImportablePythonSources:
    stripped_sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in targets),
            for_sources_types=(PythonSources, ResourcesSources, FilesSources),
            enable_codegen=True,
            strip_source_roots=True,
        )
    )
    init_injected = await Get[InitInjectedSnapshot](InjectInitRequest(stripped_sources.snapshot))
    return ImportablePythonSources(init_injected.snapshot)


def rules():
    return [
        prepare_python_sources,
        *determine_source_files.rules(),
        *inject_init_rules(),
        RootRule(Targets),
    ]
