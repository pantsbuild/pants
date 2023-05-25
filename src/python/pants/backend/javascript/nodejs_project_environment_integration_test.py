# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from dataclasses import replace
from pathlib import Path

import pytest
from _pytest.tmpdir import TempPathFactory

from pants.backend.javascript import install_node_package, package_json
from pants.backend.javascript.nodejs_project_environment import (
    NodeJsProjectEnvironment,
    NodeJsProjectEnvironmentProcess,
    NodeJSProjectEnvironmentRequest,
)
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.build_graph.address import Address
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def named_caches_dir(tmp_path_factory: TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("named_caches", numbered=False)


@pytest.fixture
def rule_runner(named_caches_dir: Path) -> RuleRunner:
    runner = RuleRunner(
        rules=[
            *install_node_package.rules(),
            QueryRule(NodeJsProjectEnvironment, (NodeJSProjectEnvironmentRequest,)),
            QueryRule(Process, (NodeJsProjectEnvironmentProcess,)),
            QueryRule(ProcessResult, (Process,)),
        ],
        target_types=[PackageJsonTarget],
        objects=dict(package_json.build_file_aliases().objects),
        bootstrap_args=[f"--named-caches-dir={named_caches_dir}"],
    )
    runner.set_options([], env_inherit={"PATH"})
    return runner


def test_pnpm_project_sandbox_provides_append_only_cache_at_expected_location(
    rule_runner: RuleRunner, named_caches_dir: Path
):
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "packageManager": "pnpm@7.5.0",
                    "scripts": {"pretend": "touch $PNPM_HOME/marker.txt"},
                }
            ),
        }
    )
    project_env = rule_runner.request(
        NodeJsProjectEnvironment,
        [NodeJSProjectEnvironmentRequest(Address("src/js", generated_name="ham"))],
    )
    process = rule_runner.request(
        Process,
        [
            NodeJsProjectEnvironmentProcess(
                project_env, ("run", "pretend"), description="Ensuring pnpm_home is preserved."
            )
        ],
    )
    process = replace(
        process, cache_scope=ProcessCacheScope.PER_SESSION
    )  # Disable caches for this process to avoid flakiness
    rule_runner.request(ProcessResult, [process])
    assert (named_caches_dir / "pnpm_home/marker.txt").is_file()
