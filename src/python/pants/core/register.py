# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

from pants.core.goals import binary, fmt, lint, repl, run, test
from pants.core.target_types import (
    AliasTarget,
    Files,
    GenericTarget,
    PrepCommand,
    RemoteSources,
    Resources,
)
from pants.core.util_rules import (
    archive,
    determine_source_files,
    distdir,
    external_tool,
    filter_empty_sources,
    pants_environment,
    strip_source_roots,
)
from pants.source import source_root


def rules():
    return [
        # goals
        *binary.rules(),
        *fmt.rules(),
        *lint.rules(),
        *repl.rules(),
        *run.rules(),
        *test.rules(),
        # util_rules
        *determine_source_files.rules(),
        *distdir.rules(),
        *filter_empty_sources.rules(),
        *strip_source_roots.rules(),
        *archive.rules(),
        *external_tool.rules(),
        *pants_environment.rules(),
        *source_root.rules(),
    ]


def target_types():
    return [AliasTarget, Files, GenericTarget, PrepCommand, RemoteSources, Resources]
