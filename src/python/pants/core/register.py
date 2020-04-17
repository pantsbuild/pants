# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

from pants.core.goals import binary, fmt, lint, repl, run, test
from pants.core.project_info import (
    cloc,
    filedeps,
    list_backends,
    list_roots,
    list_target_types,
    list_targets,
    list_targets_old,
)
from pants.core.rule_utils import (
    determine_source_files,
    distdir,
    filter_empty_sources,
    strip_source_roots,
)
from pants.core.target_types import (
    AliasTarget,
    Files,
    GenericTarget,
    PrepCommand,
    RemoteSources,
    Resources,
)
from pants.engine.target import rules as target_rules


def rules():
    return [
        *cloc.rules(),
        *binary.rules(),
        *fmt.rules(),
        *lint.rules(),
        *list_backends.rules(),
        *list_roots.rules(),
        *list_target_types.rules(),
        *list_targets.rules(),
        *list_targets_old.rules(),
        *determine_source_files.rules(),
        *filedeps.rules(),
        *repl.rules(),
        *run.rules(),
        *strip_source_roots.rules(),
        *filter_empty_sources.rules(),
        *distdir.rules(),
        *test.rules(),
        *target_rules(),
    ]


def targets2():
    return [AliasTarget, Files, GenericTarget, PrepCommand, RemoteSources, Resources]
