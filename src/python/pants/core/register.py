# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.deprecated_v1_target_types import (
    AliasTarget,
    Bundle,
    PrepCommand,
    PythonApp,
    PythonGrpcioLibrary,
    UnpackedWheels,
)
from pants.core.goals import binary, fmt, lint, package, repl, run, test, typecheck
from pants.core.target_types import ArchiveTarget, Files, GenericTarget, RelocatedFiles, Resources
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules import (
    archive,
    distdir,
    external_tool,
    filter_empty_sources,
    pants_bin,
    pants_environment,
    source_files,
    stripped_source_files,
    subprocess_environment,
)
from pants.source import source_root


def build_file_aliases():
    return BuildFileAliases(context_aware_object_factories={"bundle": Bundle})


def rules():
    return [
        # goals
        *binary.rules(),
        *fmt.rules(),
        *lint.rules(),
        *package.rules(),
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
        *pants_environment.rules(),
        *subprocess_environment.rules(),
        *source_root.rules(),
        *target_type_rules(),
    ]


def target_types():
    return [
        ArchiveTarget,
        Files,
        GenericTarget,
        Resources,
        RelocatedFiles,
        # Deprecated targets.
        AliasTarget,
        PrepCommand,
        PythonApp,
        UnpackedWheels,
        PythonGrpcioLibrary,
    ]
