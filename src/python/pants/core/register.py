# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core rules for Pants to operate correctly.

These are always activated and cannot be disabled.
"""
from pants.backend.codegen import export_codegen_goal
from pants.bsp.rules import rules as bsp_rules
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals import (
    check,
    deploy,
    export,
    fix,
    fmt,
    generate_lockfiles,
    generate_snapshots,
    lint,
    package,
    publish,
    repl,
    resolve_helpers,
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
    LockfilesGeneratorTarget,
    LockfileTarget,
    RelocatedFiles,
    ResourcesGeneratorTarget,
    ResourceSourceField,
    ResourceTarget,
    http_source,
    per_platform,
)
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules import (
    adhoc_binaries,
    archive,
    config_files,
    environments,
    external_tool,
    source_files,
    stripped_source_files,
    subprocess_environment,
    system_binaries,
)
from pants.core.util_rules.environments import (
    DockerEnvironmentTarget,
    LocalEnvironmentTarget,
    RemoteEnvironmentTarget,
)
from pants.core.util_rules.wrap_source import wrap_source_rule_and_target
from pants.engine.internals.parametrize import Parametrize
from pants.goal import anonymous_telemetry, stats_aggregator
from pants.source import source_root
from pants.vcs import git
from pants.version import PANTS_SEMVER

wrap_as_resources = wrap_source_rule_and_target(ResourceSourceField, "resources")


def rules():
    return [
        # goals
        *check.rules(),
        *deploy.rules(),
        *export.rules(),
        *export_codegen_goal.rules(),
        *fmt.rules(),
        *fix.rules(),
        *resolve_helpers.rules(),
        *generate_lockfiles.rules(),
        *generate_snapshots.rules(),
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
        *adhoc_binaries.rules(),
        *anonymous_telemetry.rules(),
        *archive.rules(),
        *config_files.rules(),
        *environments.rules(),
        *external_tool.rules(),
        *git.rules(),
        *source_files.rules(),
        *source_root.rules(),
        *stats_aggregator.rules(),
        *stripped_source_files.rules(),
        *subprocess_environment.rules(),
        *system_binaries.rules(),
        *target_type_rules(),
        *wrap_as_resources.rules,
    ]


def target_types():
    return [
        ArchiveTarget,
        DockerEnvironmentTarget,
        FilesGeneratorTarget,
        FileTarget,
        GenericTarget,
        LocalEnvironmentTarget,
        LockfilesGeneratorTarget,
        LockfileTarget,
        RelocatedFiles,
        RemoteEnvironmentTarget,
        ResourcesGeneratorTarget,
        ResourceTarget,
        *wrap_as_resources.target_types,
    ]


def build_file_aliases():
    return BuildFileAliases(
        objects={
            "PANTS_VERSION": PANTS_SEMVER,
            "http_source": http_source,
            "per_platform": per_platform,
            "parametrize": Parametrize,
        },
    )
