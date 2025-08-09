# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.javascript import install_node_package
from pants.backend.javascript.install_node_package import (
    InstalledNodePackageRequest,
    add_sources_to_installed_node_package,
)
from pants.backend.javascript.nodejs_project_environment import (
    NodeJsProjectEnvironmentProcess,
    setup_nodejs_project_environment_process,
)
from pants.backend.javascript.package_json import (
    NodeBuildScriptEntryPointField,
    NodeBuildScriptExtraEnvVarsField,
    NodePackageDependenciesField,
    NodeRunScriptEntryPointField,
    NodeRunScriptExtraEnvVarsField,
)
from pants.core.environments.target_types import EnvironmentField
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.internals.platform_rules import environment_vars_subset
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class RunNodeBuildScriptFieldSet(RunFieldSet):
    required_fields = (NodeBuildScriptEntryPointField, NodePackageDependenciesField)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    entry_point: NodeBuildScriptEntryPointField
    extra_env_vars: NodeBuildScriptExtraEnvVarsField
    environment: EnvironmentField


@dataclass(frozen=True)
class RunNodeScriptFieldSet(RunFieldSet):
    required_fields = (NodeRunScriptEntryPointField, NodePackageDependenciesField)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    entry_point: NodeRunScriptEntryPointField
    extra_env_vars: NodeRunScriptExtraEnvVarsField
    environment: EnvironmentField


@rule
async def run_node_script(
    field_set: RunNodeScriptFieldSet,
) -> RunRequest:
    installation = await add_sources_to_installed_node_package(
        InstalledNodePackageRequest(field_set.address)
    )
    target_env_vars = await environment_vars_subset(
        EnvironmentVarsRequest(field_set.extra_env_vars.value or ()), **implicitly()
    )
    package_dir = "{chroot}" + "/" + installation.project_env.package_dir()

    process = await setup_nodejs_project_environment_process(
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=(
                *installation.package_manager.current_directory_args,
                package_dir,
                "run",
                str(field_set.entry_point.value),
            ),
            description=f"Running {str(field_set.entry_point.value)}.",
            input_digest=installation.digest,
            extra_env=target_env_vars,
        ),
        **implicitly(),
    )

    return RunRequest(
        digest=process.input_digest,
        args=process.argv,
        extra_env=process.env,
        immutable_input_digests=process.immutable_input_digests,
    )


@rule
async def run_node_build_script(
    field_set: RunNodeBuildScriptFieldSet,
) -> RunRequest:
    installation = await add_sources_to_installed_node_package(
        InstalledNodePackageRequest(field_set.address)
    )
    target_env_vars = await environment_vars_subset(
        EnvironmentVarsRequest(field_set.extra_env_vars.value or ()), **implicitly()
    )
    package_dir = "{chroot}" + "/" + installation.project_env.package_dir()

    process = await setup_nodejs_project_environment_process(
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=(
                *installation.package_manager.current_directory_args,
                package_dir,
                "run",
                str(field_set.entry_point.value),
            ),
            description=f"Running {str(field_set.entry_point.value)}.",
            input_digest=installation.digest,
            extra_env=target_env_vars,
        ),
        **implicitly(),
    )

    return RunRequest(
        digest=process.input_digest,
        args=process.argv,
        extra_env=process.env,
        immutable_input_digests=process.immutable_input_digests,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *install_node_package.rules(),
        *RunNodeBuildScriptFieldSet.rules(),
        *RunNodeScriptFieldSet.rules(),
    ]
