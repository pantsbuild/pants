# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Integration tests for Podman-specific pull policy behavior in DockerImageBuildPullOptionField."""

from __future__ import annotations

import pytest

from pants.backend.docker.goals.package_image import (
    DockerImageBuildProcess,
    DockerImageRefs,
    DockerPackageFieldSet,
    ImageRefRegistry,
    ImageRefTag,
    get_docker_image_build_process,
    rules,
)
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.backend.docker.util_rules.docker_build_args import rules as build_args_rules
from pants.backend.docker.util_rules.docker_build_context import DockerBuildContext
from pants.backend.docker.util_rules.docker_build_env import DockerBuildEnvironment
from pants.backend.docker.util_rules.docker_build_env import rules as build_env_rules
from pants.engine.addresses import Address
from pants.engine.env_vars import EnvironmentVars
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.target import InvalidFieldException, WrappedTarget
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.value_interpolation import InterpolationContext, InterpolationValue


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *build_args_rules(),
            *build_env_rules(),
            QueryRule(DockerOptions, []),
        ],
        target_types=[DockerImageTarget],
    )


def _make_image_refs(address: Address) -> DockerImageRefs:
    repository = address.target_name
    return DockerImageRefs(
        [
            ImageRefRegistry(
                registry=None,
                repository=repository,
                tags=(
                    ImageRefTag(
                        template="latest",
                        formatted="latest",
                        full_name=f"{repository}:latest",
                        uses_local_alias=False,
                    ),
                ),
            )
        ]
    )


def create_test_context(rule_runner: RuleRunner, pull_value=None):
    """Helper to create a mock build context and target with specific pull value."""
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
        build_env=DockerBuildEnvironment(environment=EnvironmentVars()),
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

    # Use Podman binary
    podman_binary = DockerBinary(
        path="/bin/podman",
        fingerprint="test",
        extra_env={},
        extra_input_digests=None,
        is_podman=True,
    )

    address = Address("test")
    image_refs = _make_image_refs(address)

    result: DockerImageBuildProcess = run_rule_with_mocks(
        get_docker_image_build_process,
        rule_args=[
            DockerPackageFieldSet.create(tgt),
            docker_options,
            podman_binary,
        ],
        mock_calls={
            "pants.backend.docker.util_rules.docker_build_context.create_docker_build_context": lambda _req: build_context,
            "pants.engine.internals.graph.resolve_target": lambda _: WrappedTarget(tgt),
            "pants.backend.docker.goals.package_image.get_image_refs": lambda _: image_refs,
        },
        union_membership=UnionMembership.from_rules([]),
        show_warnings=False,
    )

    # Verify that the correct policy was used
    argv = result.process.argv
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

    # Use Docker binary (not Podman)
    docker_binary = DockerBinary(
        path="/bin/docker",
        fingerprint="test",
        extra_env={},
        extra_input_digests=None,
        is_podman=False,
    )

    address = Address("test")
    image_refs = _make_image_refs(address)

    # Should raise InvalidFieldException
    with pytest.raises(InvalidFieldException) as exc_info:
        run_rule_with_mocks(
            get_docker_image_build_process,
            rule_args=[
                DockerPackageFieldSet.create(tgt),
                docker_options,
                docker_binary,
            ],
            mock_calls={
                "pants.backend.docker.util_rules.docker_build_context.create_docker_build_context": lambda _req: build_context,
                "pants.engine.internals.graph.resolve_target": lambda _: WrappedTarget(tgt),
                "pants.backend.docker.goals.package_image.get_image_refs": lambda _: image_refs,
            },
            union_membership=UnionMembership.from_rules([]),
            show_warnings=False,
        )

    assert "string pull policies are only supported by Podman" in str(exc_info.value)
