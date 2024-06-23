# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import install_node_package
from pants.backend.javascript.install_node_package import (
    InstalledNodePackageRequest,
    InstalledNodePackageWithSource,
)
from pants.backend.javascript.nodejs_project_environment import NodeJsProjectEnvironmentProcess
from pants.backend.javascript.package_json import (
    NodeBuildScriptEntryPointField,
    NodeBuildScriptExtraEnvVarsField,
    NodePackageDependenciesField,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.selectors import Get
from pants.engine.process import Process
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class RunNodeBuildScriptFieldSet(RunFieldSet):
    required_fields = (NodeBuildScriptEntryPointField, NodePackageDependenciesField)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    entry_point: NodeBuildScriptEntryPointField
    extra_env_vars: NodeBuildScriptExtraEnvVarsField
    environment: EnvironmentField


@rule
async def run_node_build_script(
    field_set: RunNodeBuildScriptFieldSet,
) -> RunRequest:
    installation = await Get(
        InstalledNodePackageWithSource, InstalledNodePackageRequest(field_set.address)
    )
    target_env_vars = await Get(
        EnvironmentVars, EnvironmentVarsRequest(field_set.extra_env_vars.value or ())
    )

    prefix_arg = "--prefix"
    if installation.project_env.project.package_manager == "yarn":
        prefix_arg = "--cwd"

    process = await Get(
        Process,
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=(prefix_arg, "{chroot}", "run", str(field_set.entry_point.value)),
            description=f"Running {str(field_set.entry_point.value)}.",
            input_digest=installation.digest,
            extra_env=target_env_vars,
        ),
    )

    return RunRequest(
        digest=process.input_digest,
        args=process.argv,
        extra_env=process.env,
        immutable_input_digests=process.immutable_input_digests,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *install_node_package.rules(), *RunNodeBuildScriptFieldSet.rules()]
