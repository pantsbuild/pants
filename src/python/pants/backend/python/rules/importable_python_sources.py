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
from pants.rules.core.determine_source_files import LegacyAllSourceFilesRequest, SourceFiles


@dataclass(frozen=True)
class ImportablePythonSources:
    """Sources that can be imported and used by Python, e.g. with tools like Pytest or with `./pants
    run`.

    Specifically, this will strip source roots, e.g. `src/python/f.py` -> `f.py`; and it will add
    any missing `__init__.py` files to ensure that modules are recognized correctly.

    Not every file need be a Python file. For example, this can include `files()` and
    `resources()` targets.

    Not every Python application will need to request this type. For example, autoformatters like
    Black never need to actually import and run the Python code, so they do not need to use this.
    """

    snapshot: Snapshot


@rule
async def legacy_prepare_python_sources(
    hydrated_targets: HydratedTargets,
) -> ImportablePythonSources:
    stripped_sources = await Get[SourceFiles](
        LegacyAllSourceFilesRequest(
            (ht.adaptor for ht in hydrated_targets), strip_source_roots=True
        )
    )
    init_injected = await Get[InitInjectedSnapshot](InjectInitRequest(stripped_sources.snapshot))
    return ImportablePythonSources(init_injected.snapshot)


def rules():
    return [
        legacy_prepare_python_sources,
        *determine_source_files.rules(),
        *inject_init_rules(),
    ]
