# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents
from pants.jvm.goals.lockfile import GenerateJvmLockfile
from pants.jvm.goals.lockfile import rules as lockfile_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, JvmToolBase
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.util_rules import rules as util_rules
from pants.option.scope import Scope, ScopedOptions
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


class MockJvmTool(JvmToolBase):
    options_scope = "mock-tool"
    help = "Hamcrest is a mocking tool for the JVM."

    default_version = "1.3"
    default_artifacts = ("org.hamcrest:hamcrest-core:{version}",)
    default_lockfile_resource = ("pants.backend.jvm.resolve", "mock-tool.default.lockfile.txt")


async def test_jvm_tool_base_extracts_correct_coordinates() -> None:
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
            *MockJvmTool.rules(),
            QueryRule(ScopedOptions, (Scope,)),
            QueryRule(GenerateJvmLockfile, (GenerateJvmLockfileFromTool,)),
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

    opts = rule_runner.request(ScopedOptions, (Scope(str(MockJvmTool.options_scope)),))
    tool = MockJvmTool(opts.options)
    lockfile_request = rule_runner.request(
        GenerateJvmLockfile, [GenerateJvmLockfileFromTool.create(tool)]
    )
    coordinates = sorted(i.coordinate for i in lockfile_request.artifacts)
    assert coordinates == [
        Coordinate(group="junit", artifact="junit", version="4.13.2"),
        Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3"),
    ]
