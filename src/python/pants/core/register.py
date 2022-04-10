# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""
from pants.bsp.rules import rules as bsp_rules
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals import (
    check,
    export,
    fmt,
    generate_lockfiles,
    lint,
    package,
    publish,
    repl,
    run,
    tailor,
    test,
    update_build_files,
)
from pants.core.target_types import (
    ArchiveTarget,
    FilesGeneratorTarget,
    FileTarget,
    GenericTarget,
    RelocatedFiles,
    ResourcesGeneratorTarget,
    ResourceTarget,
)
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules import (
    archive,
    config_files,
    distdir,
    external_tool,
    source_files,
    stripped_source_files,
    subprocess_environment,
    system_binaries,
)
from pants.engine.internals.parametrize import Parametrize
from pants.goal import anonymous_telemetry, stats_aggregator
from pants.source import source_root
from pants.vcs import git


def rules():
    return [
        # goals
        *check.rules(),
        *export.rules(),
        *fmt.rules(),
        *generate_lockfiles.rules(),
        *lint.rules(),
        *update_build_files.rules(),
        *package.rules(),
        *publish.rules(),
        *repl.rules(),
        *run.rules(),
        *tailor.rules(),
        *test.rules(),
        *bsp_rules(),
        # util_rules
        *anonymous_telemetry.rules(),
        *archive.rules(),
        *config_files.rules(),
        *distdir.rules(),
        *external_tool.rules(),
        *git.rules(),
        *source_files.rules(),
        *source_root.rules(),
        *stats_aggregator.rules(),
        *stripped_source_files.rules(),
        *subprocess_environment.rules(),
        *system_binaries.rules(),
        *target_type_rules(),
    ]


def target_types():
    return [
        ArchiveTarget,
        FileTarget,
        FilesGeneratorTarget,
        GenericTarget,
        ResourceTarget,
        ResourcesGeneratorTarget,
        RelocatedFiles,
    ]


def build_file_aliases():
    return BuildFileAliases(
        objects={"parametrize": Parametrize},
    )
