# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

from pants.core.goals import fmt, lint, package, repl, run, tailor, test, typecheck
from pants.core.target_types import ArchiveTarget, Files, GenericTarget, RelocatedFiles, Resources
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules import (
    archive,
    config_files,
    distdir,
    external_tool,
    filter_empty_sources,
    pants_bin,
    source_files,
    stripped_source_files,
    subprocess_environment,
)
from pants.goal import anonymous_telemetry, stats_aggregator
from pants.source import source_root


def rules():
    return [
        # goals
        *fmt.rules(),
        *lint.rules(),
        *package.rules(),
        *repl.rules(),
        *run.rules(),
        *test.rules(),
        *typecheck.rules(),
        *tailor.rules(),
        # util_rules
        *config_files.rules(),
        *distdir.rules(),
        *filter_empty_sources.rules(),
        *pants_bin.rules(),
        *source_files.rules(),
        *stripped_source_files.rules(),
        *archive.rules(),
        *external_tool.rules(),
        *subprocess_environment.rules(),
        *source_root.rules(),
        *target_type_rules(),
        *anonymous_telemetry.rules(),
        *stats_aggregator.rules(),
    ]


def target_types():
    return [ArchiveTarget, Files, GenericTarget, Resources, RelocatedFiles]
