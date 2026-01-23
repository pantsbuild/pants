# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Integration tests for Podman-specific pull policy behavior in DockerImageBuildPullOptionField."""

from __future__ import annotations

import pytest

from pants.backend.docker.goals.package_image import (
    DockerPackageFieldSet,
    build_docker_image,
    rules,
)
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_args import rules as build_args_rules
from pants.backend.docker.util_rules.docker_build_env import rules as build_env_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, CreateDigest
from pants.engine.process import Process, ProcessExecutionEnvironment
from pants.engine.target import InvalidFieldException, WrappedTarget
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions, KeepSandboxes
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import QueryRule, RuleRunner, run_rule_with_mocks


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *build_args_rules(),
            *build_env_rules(),
            QueryRule(GlobalOptions, []),
            QueryRule(DockerOptions, []),
        ],
        target_types=[DockerImageTarget],
    )


def create_test_context(rule_runner: RuleRunner, pull_value=None):
    """Helper to create a mock build context and target with specific pull value."""
    from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
    from pants.backend.docker.util_rules.docker_build_context import DockerBuildContext
    from pants.backend.docker.util_rules.docker_build_env import DockerBuildEnvironment
    from pants.util.value_interpolation import InterpolationContext, InterpolationValue

    # Create BUILD file with optional pull value
    # Python booleans need to be capitalized (True/False) in BUILD files
    build_content = "docker_image(name='test'"
    if pull_value is not None:
        if isinstance(pull_value, str):
            build_content += f", pull='{pull_value}'"
        else:
            # Convert bool to string with proper capitalization
            build_content += f", pull={str(pull_value)}"
    build_content += ")"

    rule_runner.write_files(
        {
            "test/BUILD": build_content,
            "test/Dockerfile": "FROM alpine:3.16\n",
        }
    )

    tgt = rule_runner.get_target(Address("test"))

    # Mock build context
    build_context = DockerBuildContext(
        build_args=DockerBuildArgs(),
        digest=EMPTY_DIGEST,
        dockerfile="test/Dockerfile",
        build_env=DockerBuildEnvironment(environment={}),
        interpolation_context=InterpolationContext.from_dict(
            {
                "tags": InterpolationValue({}),
            }
        ),
        copy_source_vs_context_source=(("test/Dockerfile", ""),),
        stages=(),
        upstream_image_ids=(),
    )

    return tgt, build_context


@pytest.mark.parametrize(
    "policy",
    ["always", "missing", "never", "newer"],
)
def test_podman_pull_string_policies(rule_runner: RuleRunner, policy: str) -> None:
    """Test that Podman accepts all valid string pull policies."""
    tgt, build_context = create_test_context(rule_runner, pull_value=policy)

    process_args = []

    def capture_process(process: Process):
        process_args.append(process.argv)
        from pants.engine.process import FallibleProcessResult, ProcessResultMetadata

        return FallibleProcessResult(
            stdout=b"Successfully built abc123\n",
            stdout_digest=EMPTY_DIGEST,
            stderr=b"",
            stderr_digest=EMPTY_DIGEST,
            exit_code=0,
            output_digest=EMPTY_DIGEST,
            metadata=ProcessResultMetadata(
                0,
                ProcessExecutionEnvironment(
                    environment_name=None,
                    platform="linux_x86_64",
                    docker_image=None,
                    remote_execution=False,
                    remote_execution_extra_platform_properties=[],
                    execute_in_workspace=False,
                    keep_sandboxes="never",
                ),
                "ran_locally",
                0,
            ),
        )

    def mock_digest(_: CreateDigest):
        return EMPTY_DIGEST

    docker_options = create_subsystem(
        DockerOptions,
        registries={},
        default_repository="{name}",
        default_context_root="",
        build_args=[],
        build_target_stage=None,
        build_hosts=None,
        build_verbose=False,
        build_no_cache=False,
        use_buildx=False,
        env_vars=[],
    )

    global_options = rule_runner.request(GlobalOptions, [])

    # Use Podman binary
    podman_binary = DockerBinary(
        path="/bin/podman",
        fingerprint="test",
        extra_env={},
        extra_input_digests=None,
        is_podman=True,
    )

    run_rule_with_mocks(
        build_docker_image,
        rule_args=[
            DockerPackageFieldSet.create(tgt),
            docker_options,
            global_options,
            podman_binary,
            KeepSandboxes.never,
            UnionMembership.from_rules([]),
        ],
        mock_calls={
            "pants.backend.docker.util_rules.docker_build_context.create_docker_build_context": lambda _req: build_context,
            "pants.engine.internals.graph.resolve_target": lambda _: WrappedTarget(tgt),
            "pants.engine.intrinsics.execute_process": capture_process,
            "pants.engine.intrinsics.create_digest": mock_digest,
        },
        union_membership=UnionMembership.from_rules([]),
        show_warnings=False,
    )

    # Verify that the correct policy was used
    assert len(process_args) == 1
    argv = process_args[0]
    expected_flag = f"--pull={policy}"
    assert expected_flag in argv, f"Expected '{expected_flag}' in {argv}"


def test_docker_pull_string_raises_error(rule_runner: RuleRunner) -> None:
    """Test that Docker backend raises error when given a string pull policy."""
    tgt, build_context = create_test_context(rule_runner, pull_value="always")

    docker_options = create_subsystem(
        DockerOptions,
        registries={},
        default_repository="{name}",
        default_context_root="",
        build_args=[],
        build_target_stage=None,
        build_hosts=None,
        build_verbose=False,
        build_no_cache=False,
        use_buildx=False,
        env_vars=[],
    )

    global_options = rule_runner.request(GlobalOptions, [])

    # Use Docker binary (not Podman)
    docker_binary = DockerBinary(
        path="/bin/docker",
        fingerprint="test",
        extra_env={},
        extra_input_digests=None,
        is_podman=False,
    )

    def mock_digest(_: CreateDigest):
        return EMPTY_DIGEST

    # Should raise InvalidFieldException
    with pytest.raises(InvalidFieldException) as exc_info:
        run_rule_with_mocks(
            build_docker_image,
            rule_args=[
                DockerPackageFieldSet.create(tgt),
                docker_options,
                global_options,
                docker_binary,
                KeepSandboxes.never,
                UnionMembership.from_rules([]),
            ],
            mock_calls={
                "pants.backend.docker.util_rules.docker_build_context.create_docker_build_context": lambda _req: build_context,
                "pants.engine.internals.graph.resolve_target": lambda _: WrappedTarget(tgt),
                "pants.engine.intrinsics.create_digest": mock_digest,
            },
            union_membership=UnionMembership.from_rules([]),
            show_warnings=False,
        )

    assert "string pull policies are only supported by Podman" in str(exc_info.value)
