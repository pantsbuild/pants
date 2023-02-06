# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from textwrap import dedent

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.run.rules import RunNodeBuildScriptFieldSet
from pants.backend.javascript.run.rules import rules as run_rules
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.run import RunRequest
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *run_rules(),
            QueryRule(RunRequest, (RunNodeBuildScriptFieldSet,)),
        ],
        target_types=[
            *package_json.target_types(),
            JSSourceTarget,
            JSSourcesGeneratorTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )


def test_creates_run_requests_package_json_scripts(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", outputs=[]),
                        node_build_script(entry_point="compile", outputs=[]),
                        node_build_script(entry_point="transpile", outputs=[]),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "scripts": {
                        "build": "swc ./lib -d dist",
                        "transpile": "babel ./lib -d dist",
                        "compile": "tsc ./lib --emit -d bin",
                    },
                }
            ),
            "src/js/package-lock.json": json.dumps({}),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    for script in ("build", "compile", "transpile"):
        tgt = rule_runner.get_target(Address("src/js", generated_name=script))
        result = rule_runner.request(RunRequest, [RunNodeBuildScriptFieldSet.create(tgt)])

        assert result.args == ("npm", "--prefix", "{chroot}", "run", script)
