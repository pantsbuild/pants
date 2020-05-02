# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

from pants.core.goals import binary, fmt, lint, repl, run, test
from pants.core.project_info import cloc, filedeps, list_roots, list_targets, list_targets_old
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
    strip_source_roots,
)
from pants.option.options_bootstrapper import is_v2_exclusive


def rules():
    return [
        # project_info
        *cloc.rules(),
        *filedeps.rules(),
        *list_roots.rules(),
        *list_targets.rules(),
        *(list_targets_old.rules() if not is_v2_exclusive else ()),
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
    ]


def target_types():
    return [AliasTarget, Files, GenericTarget, PrepCommand, RemoteSources, Resources]
