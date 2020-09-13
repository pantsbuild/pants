# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

from pants.core.goals import binary, fmt, lint, repl, run, test, typecheck
from pants.core.target_types import Files, GenericTarget, Resources
from pants.core.util_rules import (
    archive,
    distdir,
    external_tool,
    filter_empty_sources,
    pants_bin,
    source_files,
    stripped_source_files,
    subprocess_environment,
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
        *typecheck.rules(),
        # util_rules
        *distdir.rules(),
        *filter_empty_sources.rules(),
        *pants_bin.rules(),
        *source_files.rules(),
        *stripped_source_files.rules(),
        *archive.rules(),
        *external_tool.rules(),
        *subprocess_environment.rules(),
        *source_root.rules(),
    ]


def target_types():
    return [Files, GenericTarget, Resources]
