# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, UnrecognizedResolveNamesError
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import SubsystemRule, rule
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.jvm_tool import (
    GatherJvmCoordinatesRequest,
    JvmToolBase,
    JvmToolLockfileRequest,
    JvmToolLockfileSentinel,
    determine_resolves_to_generate,
    filter_tool_lockfile_requests,
)
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


class MockJvmTool(JvmToolBase):
    options_scope = "mock-tool"

    default_version = "1.3"
    default_artifacts = ("org.hamcrest:hamcrest-core:{version}",)
    default_lockfile_resource = ("pants.backend.jvm.resolve", "mock-tool.default.lockfile.txt")
    default_lockfile_url = ""


class MockJvmToolLockfileSentinel(JvmToolLockfileSentinel):
    resolve_name = MockJvmTool.options_scope


@rule
async def generate_test_tool_lockfile_request(
    _: MockJvmToolLockfileSentinel, tool: MockJvmTool
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest.from_tool(tool)


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
            generate_test_tool_lockfile_request,
            SubsystemRule(MockJvmTool),
            QueryRule(JvmToolLockfileRequest, (MockJvmToolLockfileSentinel,)),
            QueryRule(ArtifactRequirements, (GatherJvmCoordinatesRequest,)),
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
    lockfile_request = rule_runner.request(JvmToolLockfileRequest, [MockJvmToolLockfileSentinel()])
    assert sorted(lockfile_request.artifact_inputs) == [
        "//:junit_junit",
        "org.hamcrest:hamcrest-core:1.3",
    ]

    requirements = rule_runner.request(
        ArtifactRequirements, [GatherJvmCoordinatesRequest(lockfile_request.artifact_inputs, "")]
    )
    coordinates = [i.coordinate for i in requirements]
    assert sorted(coordinates, key=lambda c: (c.group, c.artifact, c.version)) == [
        Coordinate(group="junit", artifact="junit", version="4.13.2"),
        Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3"),
    ]


def test_determine_tool_sentinels_to_generate() -> None:
    class Tool1(JvmToolLockfileSentinel):
        resolve_name = "tool1"

    class Tool2(JvmToolLockfileSentinel):
        resolve_name = "tool2"

    class Tool3(JvmToolLockfileSentinel):
        resolve_name = "tool3"

    def assert_chosen(
        requested: list[str],
        expected_tools: list[type[JvmToolLockfileSentinel]],
    ) -> None:
        tools = determine_resolves_to_generate([Tool1, Tool2, Tool3], requested)
        assert tools == expected_tools

    assert_chosen([Tool2.resolve_name], expected_tools=[Tool2])
    assert_chosen(
        [Tool1.resolve_name, Tool3.resolve_name],
        expected_tools=[Tool1, Tool3],
    )

    # If none are specifically requested, return all.
    assert_chosen([], expected_tools=[Tool1, Tool2, Tool3])

    with pytest.raises(UnrecognizedResolveNamesError):
        assert_chosen(["fake"], expected_tools=[])


def test_filter_tool_lockfile_requests() -> None:
    def create_request(name: str, lockfile_dest: str | None = None) -> JvmToolLockfileRequest:
        return JvmToolLockfileRequest(
            FrozenOrderedSet(),
            resolve_name=name,
            lockfile_dest=lockfile_dest or f"{name}.txt",
        )

    tool1 = create_request("tool1")
    tool2 = create_request("tool2")
    default_tool = create_request("default", lockfile_dest=DEFAULT_TOOL_LOCKFILE)

    def assert_filtered(
        extra_request: JvmToolLockfileRequest | None,
        *,
        resolve_specified: bool,
    ) -> None:
        requests = [tool1, tool2]
        if extra_request:
            requests.append(extra_request)
        assert filter_tool_lockfile_requests(requests, resolve_specified=resolve_specified) == [
            tool1,
            tool2,
        ]

    assert_filtered(None, resolve_specified=False)
    assert_filtered(None, resolve_specified=True)

    assert_filtered(default_tool, resolve_specified=False)
    with pytest.raises(ValueError) as exc:
        assert_filtered(default_tool, resolve_specified=True)
    assert f"`[{default_tool.resolve_name}].lockfile` is set to `{DEFAULT_TOOL_LOCKFILE}`" in str(
        exc.value
    )
