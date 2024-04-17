# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, GenerateToolLockfileSentinel
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import rule
from pants.jvm.goals.lockfile import GenerateJvmLockfile
from pants.jvm.goals.lockfile import rules as lockfile_rules
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, JvmToolBase
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


class MockJvmTool(JvmToolBase):
    options_scope = "mock-tool"
    help = "Hamcrest is a mocking tool for the JVM."

    default_version = "1.3"
    default_artifacts = ("org.hamcrest:hamcrest-core:{version}",)
    default_lockfile_resource = ("pants.backend.jvm.resolve", "mock-tool.default.lockfile.txt")


class MockJvmToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = MockJvmTool.options_scope


class MockInternalToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = "mock-internal-tool"


@rule
def generate_test_tool_lockfile_request(
    _: MockJvmToolLockfileSentinel, tool: MockJvmTool
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


@rule
def generate_internal_test_tool_lockfile_request(
    _: MockInternalToolLockfileSentinel,
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool(
        artifact_inputs=FrozenOrderedSet(
            {
                "com.google.code.gson:gson:2.9.0",
            }
        ),
        artifact_option_name="n/a",
        lockfile_option_name="n/a",
        resolve_name=MockInternalToolLockfileSentinel.resolve_name,
        read_lockfile_dest=DEFAULT_TOOL_LOCKFILE,
        write_lockfile_dest="mock-write-lockfile.lock",
        default_lockfile_resource=("pants.backend.jvm.resolve", "mock-internal-tool.lock"),
    )


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
            generate_internal_test_tool_lockfile_request,
            *MockJvmTool.rules(),
            QueryRule(GenerateJvmLockfile, (MockJvmToolLockfileSentinel,)),
            QueryRule(GenerateJvmLockfile, (MockInternalToolLockfileSentinel,)),
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
    lockfile_request = rule_runner.request(GenerateJvmLockfile, [MockJvmToolLockfileSentinel()])
    coordinates = sorted(i.coordinate for i in lockfile_request.artifacts)
    assert coordinates == [
        Coordinate(group="junit", artifact="junit", version="4.13.2"),
        Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3"),
    ]

    # Ensure that an internal-only tool will not have a lockfile generated.
    default_lockfile_result = rule_runner.request(
        GenerateJvmLockfile, [MockInternalToolLockfileSentinel()]
    )
    assert default_lockfile_result.lockfile_dest == DEFAULT_TOOL_LOCKFILE
