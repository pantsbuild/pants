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
from pants.backend.javascript.package_json import (
    NodeBuildScriptEntryPointField,
    NodeBuildScriptOutputsField,
    NodePackageDependenciesField,
)
from pants.backend.javascript.subsystems.nodejs import NodeJS, NodeJSProcessEnvironment
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.environments import EnvironmentField
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class RunNodeBuildScriptFieldSet(RunFieldSet):
    required_fields = (NodeBuildScriptEntryPointField, NodePackageDependenciesField)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    entry_point: NodeBuildScriptEntryPointField
    output_path: NodeBuildScriptOutputsField
    environment: EnvironmentField


@rule
async def run_node_build_script(
    field_set: RunNodeBuildScriptFieldSet,
    nodejs: NodeJS,
    nodejs_environment: NodeJSProcessEnvironment,
    platform: Platform,
) -> RunRequest:
    installed = await Get(
        InstalledNodePackageWithSource, InstalledNodePackageRequest(field_set.address)
    )
    downloaded_nodejs = await Get(
        DownloadedExternalTool, ExternalToolRequest, nodejs.get_request(platform)
    )

    immutable_input_digests = {NodeJSProcessEnvironment.base_bin_dir: downloaded_nodejs.digest}
    return RunRequest(
        digest=installed.digest,
        args=("npm", "--prefix", "{chroot}", "run", str(field_set.entry_point.value)),
        extra_env=nodejs_environment.to_env_dict(),
        immutable_input_digests=immutable_input_digests,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *install_node_package.rules(), *RunNodeBuildScriptFieldSet.rules()]
