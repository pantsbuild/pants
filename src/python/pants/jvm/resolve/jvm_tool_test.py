# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

from pants.core.goals.generate_lockfiles import ToolLockfileSentinel
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, SubsystemRule, rule
from pants.jvm.goals.lockfile import JvmLockfileRequest, JvmLockfileRequestFromTool
from pants.jvm.goals.lockfile import rules as lockfile_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.common import Coordinate
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


class MockJvmTool(JvmToolBase):
    options_scope = "mock-tool"
    help = "Hamcrest is a mocking tool for the JVM."

    default_version = "1.3"
    default_artifacts = ("org.hamcrest:hamcrest-core:{version}",)
    default_lockfile_resource = ("pants.backend.jvm.resolve", "mock-tool.default.lockfile.txt")
    default_lockfile_url = ""


class MockJvmToolLockfileSentinel(ToolLockfileSentinel):
    options_scope = MockJvmTool.options_scope


@rule
async def generate_test_tool_lockfile_request(
    _: MockJvmToolLockfileSentinel, tool: MockJvmTool
) -> JvmLockfileRequest:
    return await Get(JvmLockfileRequest, JvmLockfileRequestFromTool(tool))


def test_jvm_tool_base_extracts_correct_coordinates() -> None:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
            *jvm_tool.rules(),
            *lockfile_rules(),
            generate_test_tool_lockfile_request,
            SubsystemRule(MockJvmTool),
            QueryRule(JvmLockfileRequest, (MockJvmToolLockfileSentinel,)),
            QueryRule(DigestContents, (Digest,)),
        ],
        target_types=[JvmArtifactTarget],
    )
    rule_runner.set_options(
        args=[
            "--mock-tool-artifacts=//:junit_junit",
            "--mock-tool-lockfile=/dev/null",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                """\
            jvm_artifact(
              name="junit_junit",
              group="junit",
              artifact="junit",
              version="4.13.2",
            )
            """
            )
        }
    )
    lockfile_request = rule_runner.request(JvmLockfileRequest, [MockJvmToolLockfileSentinel()])
    coordinates = sorted(i.coordinate for i in lockfile_request.artifacts)
    assert coordinates == [
        Coordinate(group="junit", artifact="junit", version="4.13.2"),
        Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3"),
    ]
