# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import textwrap

import pytest

from pants.backend.python.subsystems.python_tool_base import DEFAULT_TOOL_LOCKFILE
from pants.backend.python.target_types import UnrecognizedResolveNamesError
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents, FileDigest
from pants.engine.rules import SubsystemRule, rule
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.jvm_tool import (
    JvmToolBase,
    JvmToolLockfile,
    JvmToolLockfileRequest,
    JvmToolLockfileSentinel,
    determine_resolves_to_generate,
    filter_tool_lockfile_requests,
)
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.docutil import git_url
from pants.util.ordered_set import FrozenOrderedSet

HAMCREST_COORD = Coordinate(
    group="org.hamcrest",
    artifact="hamcrest-core",
    version="1.3",
)


class MockJvmTool(JvmToolBase):
    options_scope = "mock-tool"

    default_version = "1.3"
    default_artifacts = [
        "org.hamcrest:hamcrest-core:{version}",
    ]
    default_lockfile_resource = ("pants.backend.jvm.resolve", "mock-tool.default.lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/jvm/resolve/mock-tool.default.lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)


class MockJvmToolLockfileSentinel(JvmToolLockfileSentinel):
    options_scope = MockJvmTool.options_scope


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
            QueryRule(JvmToolLockfile, (JvmToolLockfileRequest,)),
            QueryRule(DigestContents, (Digest,)),
        ],
        target_types=[JvmDependencyLockfile, JvmArtifact],
    )
    rule_runner.set_options(
        args=[
            "--mock-tool-artifacts=//:junit_junit",
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

    tool_lockfile = rule_runner.request(JvmToolLockfile, [lockfile_request])
    assert tool_lockfile.resolve_name == "mock-tool"

    lockfile_digest_contents = rule_runner.request(DigestContents, [tool_lockfile.digest])
    assert len(lockfile_digest_contents) == 1
    lockfile_content = lockfile_digest_contents[0]
    assert (
        lockfile_content.path
        == "src/python/pants/backend/jvm/resolve/mock-tool.default.lockfile.txt"
    )
    lockfile_json = json.loads(lockfile_content.content)
    actual_lockfile = CoursierResolvedLockfile.from_json_dict(lockfile_json)
    assert actual_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(group="junit", artifact="junit", version="4.13.2"),
                file_name="junit_junit_4.13.2.jar",
                direct_dependencies=Coordinates([HAMCREST_COORD]),
                dependencies=Coordinates([HAMCREST_COORD]),
                file_digest=FileDigest(
                    fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
                    serialized_bytes_length=384581,
                ),
            ),
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
                file_name="org.hamcrest_hamcrest-core_1.3.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            ),
        )
    )


def test_determine_tool_sentinels_to_generate() -> None:
    class Tool1(JvmToolLockfileSentinel):
        options_scope = "tool1"

    class Tool2(JvmToolLockfileSentinel):
        options_scope = "tool2"

    class Tool3(JvmToolLockfileSentinel):
        options_scope = "tool3"

    def assert_chosen(
        requested: list[str],
        expected_tools: list[type[JvmToolLockfileSentinel]],
    ) -> None:
        tools = determine_resolves_to_generate([Tool1, Tool2, Tool3], requested)
        assert tools == expected_tools

    assert_chosen([Tool2.options_scope], expected_tools=[Tool2])
    assert_chosen(
        [Tool1.options_scope, Tool3.options_scope],
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
