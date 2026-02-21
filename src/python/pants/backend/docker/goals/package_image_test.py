# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os.path
from collections import namedtuple
from collections.abc import Callable
from textwrap import dedent
from typing import Any, ContextManager, cast

import pytest

from pants.backend.docker.goals.package_image import (
    DockerBuildTargetStageError,
    DockerImageBuildProcess,
    DockerImageOptionValueError,
    DockerImageRefs,
    DockerImageTagValueError,
    DockerInfoV1,
    DockerPackageFieldSet,
    DockerRepositoryNameError,
    GetImageRefsRequest,
    ImageRefRegistry,
    ImageRefTag,
    build_docker_image,
    get_docker_image_build_process,
    get_image_refs,
    parse_image_id_from_docker_build_output,
    rules,
)
from pants.backend.docker.package_types import (
    DockerPushOnPackageBehavior,
    DockerPushOnPackageException,
)
from pants.backend.docker.registries import DockerRegistries, DockerRegistryOptions
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo
from pants.backend.docker.target_types import (
    DockerImageTags,
    DockerImageTagsField,
    DockerImageTagsRequest,
    DockerImageTarget,
)
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
)
from pants.backend.docker.util_rules.docker_build_args import rules as build_args_rules
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.docker.util_rules.docker_build_env import (
    DockerBuildEnvironment,
    DockerBuildEnvironmentRequest,
)
from pants.backend.docker.util_rules.docker_build_env import rules as build_env_rules
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_FILE_DIGEST,
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    FileContent,
    Snapshot,
)
from pants.engine.platform import Platform
from pants.engine.process import (
    FallibleProcessResult,
    Process,
    ProcessExecutionEnvironment,
    ProcessExecutionFailure,
    ProcessResultMetadata,
)
from pants.engine.target import InvalidFieldException, WrappedTarget
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import GlobalOptions, KeepSandboxes
from pants.testutil.option_util import create_subsystem
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.frozendict import FrozenDict
from pants.util.value_interpolation import InterpolationContext, InterpolationError


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *build_args_rules(),
            *build_env_rules(),
            QueryRule(GlobalOptions, []),
            QueryRule(DockerOptions, []),
            QueryRule(DockerBuildArgs, [DockerBuildArgsRequest]),
            QueryRule(DockerBuildEnvironment, [DockerBuildEnvironmentRequest]),
        ],
        target_types=[DockerImageTarget],
    )


class DockerImageTagsRequestPlugin(DockerImageTagsRequest):
    pass


def _create_build_context_mock(
    rule_runner: RuleRunner,
    address: Address,
    build_context_snapshot: Snapshot,
    copy_sources: tuple[str, ...],
    copy_build_args,
    version_tags: tuple[str, ...],
):
    """Create a mock function for create_docker_build_context."""
    tgt = rule_runner.get_target(address)

    def build_context_mock(request: DockerBuildContextRequest) -> DockerBuildContext:
        return DockerBuildContext.create(
            snapshot=build_context_snapshot,
            upstream_image_ids=[],
            dockerfile_info=DockerfileInfo(
                request.address,
                digest=EMPTY_DIGEST,
                source=os.path.join(address.spec_path, "Dockerfile"),
                copy_source_paths=copy_sources,
                copy_build_args=copy_build_args,
                version_tags=version_tags,
            ),
            build_args=rule_runner.request(DockerBuildArgs, [DockerBuildArgsRequest(tgt)]),
            build_env=rule_runner.request(
                DockerBuildEnvironment, [DockerBuildEnvironmentRequest(tgt)]
            ),
        )

    return build_context_mock


def _setup_docker_options(rule_runner: RuleRunner, options: dict | None) -> DockerOptions:
    """Setup DockerOptions with sensible defaults."""
    if options:
        opts = options.copy()
        opts.setdefault("registries", {})
        opts.setdefault("default_repository", "{name}")
        opts.setdefault("default_context_root", "")
        opts.setdefault("build_args", [])
        opts.setdefault("build_target_stage", None)
        opts.setdefault("build_hosts", None)
        opts.setdefault("build_verbose", False)
        opts.setdefault("build_no_cache", False)
        opts.setdefault("use_buildx", False)
        opts.setdefault("env_vars", [])
        opts.setdefault("suggest_renames", True)
        opts.setdefault("push_on_package", DockerPushOnPackageBehavior.WARN)
        return create_subsystem(DockerOptions, **opts)
    else:
        return rule_runner.request(DockerOptions, [])


def _create_union_membership() -> UnionMembership:
    """Create union membership for Docker image tags plugin."""
    return UnionMembership.from_rules(
        [UnionRule(DockerImageTagsRequest, DockerImageTagsRequestPlugin)]
    )


def assert_build_process(
    rule_runner: RuleRunner,
    address: Address,
    *,
    options: dict | None = None,
    build_process_assertions: Callable[[DockerImageBuildProcess], None] | None = None,
    copy_sources: tuple[str, ...] = (),
    copy_build_args=(),
    build_context_snapshot: Snapshot = EMPTY_SNAPSHOT,
    version_tags: tuple[str, ...] = (),
    image_refs: DockerImageRefs | None = None,
) -> DockerImageBuildProcess:
    """Test helper for get_docker_image_build_process rule.

    Tests Process construction without execution. Returns DockerImageBuildProcess for validation.
    Tests can access result.process for Process-specific assertions.
    """
    tgt = rule_runner.get_target(address)

    # Auto-generate image_refs if not provided (same logic as old assert_build)
    if image_refs is None:
        repository = address.target_name
        image_tags = tgt.get(DockerImageTagsField).value
        tags_to_use = ("latest",) if image_tags is None else image_tags
        image_refs = DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository=repository,
                    tags=tuple(
                        ImageRefTag(
                            template=tag,
                            formatted=tag,
                            full_name=f"{repository}:{tag}",
                            uses_local_alias=False,
                        )
                        for tag in tags_to_use
                    ),
                )
            ]
        )

    build_context_mock = _create_build_context_mock(
        rule_runner, address, build_context_snapshot, copy_sources, copy_build_args, version_tags
    )
    docker_options = _setup_docker_options(rule_runner, options)

    result = run_rule_with_mocks(
        get_docker_image_build_process,
        rule_args=[
            DockerPackageFieldSet.create(tgt),
            docker_options,
            DockerBinary("/dummy/docker"),
        ],
        mock_calls={
            "pants.backend.docker.util_rules.docker_build_context.create_docker_build_context": build_context_mock,
            "pants.engine.internals.graph.resolve_target": lambda _: WrappedTarget(tgt),
            "pants.backend.docker.goals.package_image.get_image_refs": lambda _: image_refs,
        },
        union_membership=_create_union_membership(),
        show_warnings=False,
    )

    # Run optional assertions
    if build_process_assertions:
        build_process_assertions(result)

    return result


def assert_get_image_refs(
    rule_runner: RuleRunner,
    address: Address,
    *,
    options: dict | None = None,
    expected_refs: DockerImageRefs | None = None,
    version_tags: tuple[str, ...] = (),
    plugin_tags: tuple[str, ...] = (),
    copy_sources: tuple[str, ...] = (),
    copy_build_args=(),
    build_context_snapshot: Snapshot = EMPTY_SNAPSHOT,
    build_upstream_images: bool = True,
) -> DockerImageRefs:
    """Test helper for get_image_refs rule.

    Returns DockerImageRefs for validation. Optionally asserts against expected_refs.
    """
    tgt = rule_runner.get_target(address)

    build_context_mock = _create_build_context_mock(
        rule_runner, address, build_context_snapshot, copy_sources, copy_build_args, version_tags
    )
    docker_options = _setup_docker_options(rule_runner, options)
    union_membership = _create_union_membership()

    field_set = DockerPackageFieldSet.create(tgt)
    result = run_rule_with_mocks(
        get_image_refs,
        rule_args=[
            GetImageRefsRequest(
                field_set=field_set,
                build_upstream_images=build_upstream_images,
            ),
            docker_options,
            union_membership,
        ],
        mock_calls={
            "pants.backend.docker.util_rules.docker_build_context.create_docker_build_context": build_context_mock,
            "pants.engine.internals.graph.resolve_target": lambda *_, **__: WrappedTarget(tgt),
            "pants.backend.docker.target_types.get_docker_image_tags": lambda *_,
            **__: DockerImageTags(plugin_tags),
        },
        union_membership=union_membership,
    )

    if expected_refs is not None:
        assert result == expected_refs

    return result


def test_get_image_refs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\

                docker_image(
                  name="test1",
                  image_tags=["1.2.3"],
                  repository="{directory}/{name}",
                )
                docker_image(
                  name="test2",
                  image_tags=["1.2.3"],
                )
                docker_image(
                  name="test3",
                  image_tags=["1.2.3"],
                  repository="{parent_directory}/{directory}/{name}",
                )
                docker_image(
                  name="test4",
                  image_tags=["1.2.3"],
                  repository="{directory}/four/test-four",
                )
                docker_image(
                  name="test5",
                  image_tags=["latest", "alpha-1.0", "alpha-1"],
                )
                docker_image(
                  name="test6",
                  image_tags=["1.2.3"],
                  repository="xyz/{full_directory}/{name}",
                )
                docker_image(
                  name="err1",
                  repository="{bad_template}",
                )
                """
            ),
            "docker/test/Dockerfile": "FROM python:3.8",
        }
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="test1"),
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository="test/test1",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="test/test1:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )
    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="test2"),
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository="test2",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="test2:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )
    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="test3"),
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository="docker/test/test3",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="docker/test/test3:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="test4"),
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository="test/four/test-four",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="test/four/test-four:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="test5"),
        options=dict(default_repository="{directory}/{name}"),
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository="test/test5",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            full_name="test/test5:latest",
                            uses_local_alias=False,
                        ),
                        ImageRefTag(
                            template="alpha-1.0",
                            formatted="alpha-1.0",
                            full_name="test/test5:alpha-1.0",
                            uses_local_alias=False,
                        ),
                        ImageRefTag(
                            template="alpha-1",
                            formatted="alpha-1",
                            full_name="test/test5:alpha-1",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="test6"),
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository="xyz/docker/test/test6",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="xyz/docker/test/test6:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    err1 = (
        r"Invalid value for the `repository` field of the `docker_image` target at "
        r"docker/test:err1: '{bad_template}'\.\n\nThe placeholder 'bad_template' is unknown\. "
        r"Try with one of: build_args, default_repository, directory, full_directory, name, "
        r"pants, parent_directory, tags, target_repository\."
    )
    with pytest.raises(DockerRepositoryNameError, match=err1):
        assert_get_image_refs(
            rule_runner,
            Address("docker/test", target_name="err1"),
        )


def test_get_image_refs_with_registries(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(name="addr1", image_tags=["1.2.3"], registries=["myregistry1domain:port"])
                docker_image(name="addr2", image_tags=["1.2.3"], registries=["myregistry2domain:port"])
                docker_image(name="addr3", image_tags=["1.2.3"], registries=["myregistry3domain:port"])
                docker_image(name="alias1", image_tags=["1.2.3"], registries=["@reg1"])
                docker_image(name="alias2", image_tags=["1.2.3"], registries=["@reg2"])
                docker_image(name="alias3", image_tags=["1.2.3"], registries=["reg3"])
                docker_image(name="unreg", image_tags=["1.2.3"], registries=[])
                docker_image(name="def", image_tags=["1.2.3"])
                docker_image(name="multi", image_tags=["1.2.3"], registries=["@reg2", "@reg1"])
                docker_image(name="extra_tags", image_tags=["1.2.3"], registries=["@reg1", "@extra"])
                """
            ),
            "docker/test/Dockerfile": "FROM python:3.8",
        }
    )

    options = {
        "default_repository": "{name}",
        "registries": {
            "reg1": {"address": "myregistry1domain:port"},
            "reg2": {"address": "myregistry2domain:port", "default": True},
            "extra": {"address": "extra", "extra_image_tags": ["latest"]},
        },
    }

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="addr1"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="myregistry1domain:port", alias="reg1"),
                    repository="addr1",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry1domain:port/addr1:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )
    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="addr2"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        address="myregistry2domain:port", alias="reg2", default=True
                    ),
                    repository="addr2",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry2domain:port/addr2:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="addr3"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="myregistry3domain:port"),
                    repository="addr3",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry3domain:port/addr3:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="alias1"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(alias="reg1", address="myregistry1domain:port"),
                    repository="alias1",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry1domain:port/alias1:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="alias2"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        address="myregistry2domain:port", alias="reg2", default=True
                    ),
                    repository="alias2",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry2domain:port/alias2:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="alias3"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="reg3"),
                    repository="alias3",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="reg3/alias3:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="unreg"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=None,
                    repository="unreg",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="unreg:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="def"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        address="myregistry2domain:port", alias="reg2", default=True
                    ),
                    repository="def",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry2domain:port/def:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )
    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="multi"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        address="myregistry2domain:port", alias="reg2", default=True
                    ),
                    repository="multi",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry2domain:port/multi:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
                ImageRefRegistry(
                    registry=DockerRegistryOptions(alias="reg1", address="myregistry1domain:port"),
                    repository="multi",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry1domain:port/multi:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )

    assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="extra_tags"),
        options=options,
        expected_refs=DockerImageRefs(
            [
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="myregistry1domain:port", alias="reg1"),
                    repository="extra_tags",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="myregistry1domain:port/extra_tags:1.2.3",
                            uses_local_alias=False,
                        ),
                    ),
                ),
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        alias="extra", address="extra", extra_image_tags=("latest",)
                    ),
                    repository="extra_tags",
                    tags=(
                        ImageRefTag(
                            template="1.2.3",
                            formatted="1.2.3",
                            full_name="extra/extra_tags:1.2.3",
                            uses_local_alias=False,
                        ),
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            full_name="extra/extra_tags:latest",
                            uses_local_alias=False,
                        ),
                    ),
                ),
            ]
        ),
    )


def test_dynamic_image_version(rule_runner: RuleRunner) -> None:
    interpolation_context = InterpolationContext.from_dict(
        {
            "baseimage": {"tag": "3.8"},
            "stage0": {"tag": "3.8"},
            "interim": {"tag": "latest"},
            "stage2": {"tag": "latest"},
            "output": {"tag": "1-1"},
        }
    )

    def assert_tags(name: str, *expect_tags: str) -> None:
        tgt = rule_runner.get_target(Address("docker/test", target_name=name))
        fs = DockerPackageFieldSet.create(tgt)
        image_refs = fs.image_refs(
            "image",
            DockerRegistries.from_dict({}),
            interpolation_context,
        )
        tags = tuple(t.full_name for r in image_refs for t in r.tags)
        assert expect_tags == tags

    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(name="ver_1")
                docker_image(
                  name="ver_2",
                  image_tags=["{baseimage.tag}-{stage2.tag}", "beta"]
                )
                docker_image(name="err_1", image_tags=["{unknown_stage}"])
                docker_image(name="err_2", image_tags=["{stage0.unknown_value}"])
                """
            ),
        }
    )

    assert_tags("ver_1", "image:latest")
    assert_tags("ver_2", "image:3.8-latest", "image:beta")

    err_1 = (
        r"Invalid value for the `image_tags` field of the `docker_image` target at "
        r"docker/test:err_1: '{unknown_stage}'\.\n\n"
        r"The placeholder 'unknown_stage' is unknown\. Try with one of: baseimage, interim, "
        r"output, stage0, stage2\."
    )
    with pytest.raises(DockerImageTagValueError, match=err_1):
        assert_tags("err_1")

    err_2 = (
        r"Invalid value for the `image_tags` field of the `docker_image` target at "
        r"docker/test:err_2: '{stage0.unknown_value}'\.\n\n"
        r"The placeholder 'unknown_value' is unknown\. Try with one of: tag\."
    )
    with pytest.raises(DockerImageTagValueError, match=err_2):
        assert_tags("err_2")


def test_docker_build_process_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="env1", image_tags=["1.2.3"])'}
    )
    rule_runner.set_options(
        [],
        env={
            "INHERIT": "from Pants env",
            "PANTS_DOCKER_ENV_VARS": '["VAR=value", "INHERIT"]',
        },
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--tag",
            "env1:1.2.3",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )
        assert result.process.env == FrozenDict(
            {
                "INHERIT": "from Pants env",
                "VAR": "value",
                "__UPSTREAM_IMAGE_IDS": "",
            }
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="env1"),
        build_process_assertions=check_build_process,
    )


def test_build_docker_image(rule_runner: RuleRunner) -> None:
    """Test build_docker_image rule orchestration and metadata creation."""
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="img1", image_tags=["1.2.3"])'}
    )

    tgt = rule_runner.get_target(Address("docker/test", target_name="img1"))
    under_test_fs = DockerPackageFieldSet.create(tgt)
    metadata_file_path: list[str] = []
    metadata_file_contents: list[bytes] = []

    # Create mock DockerImageBuildProcess
    image_refs = DockerImageRefs(
        [
            ImageRefRegistry(
                registry=None,
                repository="img1",
                tags=(
                    ImageRefTag(
                        template="1.2.3",
                        formatted="1.2.3",
                        full_name="img1:1.2.3",
                        uses_local_alias=False,
                    ),
                ),
            )
        ]
    )

    process = Process(
        argv=(
            "/dummy/docker",
            "build",
            "--tag",
            "img1:1.2.3",
            "--pull=False",
            "--file",
            "docker/test/Dockerfile",
            ".",
        ),
        description="docker build",
        input_digest=EMPTY_DIGEST,
    )

    build_context = DockerBuildContext.create(
        snapshot=EMPTY_SNAPSHOT,
        upstream_image_ids=[],
        dockerfile_info=DockerfileInfo(
            tgt.address,
            digest=EMPTY_DIGEST,
            source="docker/test/Dockerfile",
        ),
        build_args=DockerBuildArgs(()),
        build_env=DockerBuildEnvironment.create({}),
    )

    mock_build_process = DockerImageBuildProcess(
        process=process,
        context=build_context,
        context_root=".",
        image_refs=image_refs,
        tags=("img1:1.2.3",),
    )

    # Mock get_docker_image_build_process to return our mock
    def mock_get_build_process(field_set: DockerPackageFieldSet) -> DockerImageBuildProcess:
        assert field_set == under_test_fs
        return mock_build_process

    # Mock execute_process to return success with image ID
    def mock_execute_process(_process: Process) -> FallibleProcessResult:
        return FallibleProcessResult(
            exit_code=0,
            stdout=b"Successfully built abc123\n",
            stderr=b"",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            output_digest=EMPTY_DIGEST,
            metadata=ProcessResultMetadata(
                0,
                ProcessExecutionEnvironment(
                    environment_name=None,
                    platform=Platform.create_for_localhost().value,
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

    # Mock create_digest to capture metadata
    def mock_create_digest(request: CreateDigest) -> Digest:
        assert len(request) == 1
        assert isinstance(request[0], FileContent)
        metadata_file_path.append(request[0].path)
        metadata_file_contents.append(request[0].content)
        return EMPTY_DIGEST

    docker_options = _setup_docker_options(rule_runner, None)
    global_options = rule_runner.request(GlobalOptions, [])

    # Execute the rule
    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[
            under_test_fs,
            docker_options,
            global_options,
            DockerBinary("/dummy/docker"),
            KeepSandboxes.never,
        ],
        mock_calls={
            "pants.backend.docker.goals.package_image.get_docker_image_build_process": mock_get_build_process,
            "pants.engine.intrinsics.execute_process": mock_execute_process,
            "pants.engine.intrinsics.create_digest": mock_create_digest,
        },
        show_warnings=False,
    )

    # Validate BuiltPackage result
    assert result.digest == EMPTY_DIGEST
    assert len(result.artifacts) == 1
    assert len(metadata_file_path) == 1
    assert result.artifacts[0].relpath == metadata_file_path[0]

    # Validate metadata file content
    metadata = json.loads(metadata_file_contents[0])
    assert metadata["version"] == 1
    assert metadata["image_id"] == "abc123"
    assert isinstance(metadata["registries"], list)
    assert len(metadata["registries"]) == 1
    assert metadata["registries"][0]["repository"] == "img1"
    assert metadata["registries"][0]["tags"][0]["tag"] == "1.2.3"


def test_docker_build_pull(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"docker/test/BUILD": 'docker_image(name="args1", pull=True)'})

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=True",
            "--tag",
            "args1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="args1"),
        build_process_assertions=check_build_process,
    )


def test_docker_build_squash(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
            docker_image(name="args1", squash=True)
            docker_image(name="args2", squash=False)
            """
            )
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--squash",
            "--tag",
            "args1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    def check_build_process_no_squash(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--tag",
            "args2:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="args1"),
        build_process_assertions=check_build_process,
    )
    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="args2"),
        build_process_assertions=check_build_process_no_squash,
    )


def test_docker_build_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="args1", image_tags=["1.2.3"])'}
    )
    rule_runner.set_options(
        [],
        env={
            "INHERIT": "from Pants env",
            "PANTS_DOCKER_BUILD_ARGS": '["VAR=value", "INHERIT"]',
        },
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--tag",
            "args1:1.2.3",
            "--build-arg",
            "INHERIT",
            "--build-arg",
            "VAR=value",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

        # Check that we pull in name only args via env.
        assert result.process.env == FrozenDict(
            {
                "INHERIT": "from Pants env",
                "__UPSTREAM_IMAGE_IDS": "",
            }
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="args1"),
        build_process_assertions=check_build_process,
    )


def test_docker_image_version_from_build_arg(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="ver1", image_tags=["{build_args.VERSION}"])'}
    )
    rule_runner.set_options(
        [],
        env={
            "PANTS_DOCKER_BUILD_ARGS": '["VERSION=1.2.3"]',
        },
    )

    refs = assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="ver1"),
    )
    assert len(refs) == 1
    assert refs[0].registry is None
    assert refs[0].repository == "ver1"
    assert len(refs[0].tags) == 1
    assert refs[0].tags[0].template == "{build_args.VERSION}"
    assert refs[0].tags[0].formatted == "1.2.3"
    assert refs[0].tags[0].full_name == "ver1:1.2.3"


def test_docker_repository_from_build_arg(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"docker/test/BUILD": 'docker_image(name="image", repository="{build_args.REPO}")'}
    )
    rule_runner.set_options(
        [],
        env={
            "PANTS_DOCKER_BUILD_ARGS": '["REPO=test/image"]',
        },
    )

    refs = assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="image"),
    )
    assert refs[0].repository == "test/image"
    assert refs[0].tags[0].formatted == "latest"
    assert refs[0].tags[0].full_name == "test/image:latest"


def test_docker_extra_build_args_field(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  extra_build_args=[
                    "FROM_ENV",
                    "SET=value",
                    "DEFAULT2=overridden",
                  ]
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--docker-build-args=DEFAULT1=global1",
            "--docker-build-args=DEFAULT2=global2",
        ],
        env={
            "FROM_ENV": "env value",
            "SET": "no care",
        },
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--build-arg",
            "DEFAULT1=global1",
            "--build-arg",
            "DEFAULT2=overridden",
            "--build-arg",
            "FROM_ENV",
            "--build-arg",
            "SET=value",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

        assert result.process.env == FrozenDict(
            {
                "FROM_ENV": "env value",
                "__UPSTREAM_IMAGE_IDS": "",
            }
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


def test_docker_build_secrets_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  secrets={
                    "system-secret": "/var/run/secrets/mysecret",
                    "project-secret": "secrets/mysecret",
                    "target-secret": "./mysecret",
                  }
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--secret",
            "id=system-secret,src=/var/run/secrets/mysecret",
            "--secret",
            f"id=project-secret,src={rule_runner.build_root}/secrets/mysecret",
            "--secret",
            f"id=target-secret,src={rule_runner.build_root}/docker/test/mysecret",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


def test_docker_build_ssh_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  ssh=["default"],
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--ssh",
            "default",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


def test_docker_build_no_cache_option(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [],
        env={
            "PANTS_DOCKER_BUILD_NO_CACHE": "true",
        },
    )
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--no-cache",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


def test_docker_build_hosts_option(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [],
        env={
            "PANTS_DOCKER_BUILD_HOSTS": '{"global": "9.9.9.9"}',
        },
    )
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  extra_build_hosts={"docker": "10.180.0.1", "docker2": "10.180.0.2"},
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--add-host",
            "global:9.9.9.9",
            "--add-host",
            "docker:10.180.0.1",
            "--add-host",
            "docker2:10.180.0.2",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


def test_docker_cache_to_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  cache_to={"type": "local", "dest": "/tmp/docker/pants-test-cache"},
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "buildx",
            "build",
            "--cache-to=type=local,dest=/tmp/docker/pants-test-cache",
            "--output=type=docker",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
        options=dict(use_buildx=True),
    )


def test_docker_cache_from_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  cache_from=[{"type": "local", "dest": "/tmp/docker/pants-test-cache1"}, {"type": "local", "dest": "/tmp/docker/pants-test-cache2"}],
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "buildx",
            "build",
            "--cache-from=type=local,dest=/tmp/docker/pants-test-cache1",
            "--cache-from=type=local,dest=/tmp/docker/pants-test-cache2",
            "--output=type=docker",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
        options=dict(use_buildx=True),
    )


@pytest.mark.parametrize(
    ["output", "expected_output_arg"],
    [
        (None, "--output=type=docker"),
        ({"type": "registry"}, "--output=type=registry"),
        ({"type": "image", "push": "true"}, "--output=type=image,push=true"),
    ],
)
def test_docker_output_option(
    rule_runner: RuleRunner, output: dict | None, expected_output_arg: str
) -> None:
    """Testing non-default output type 'image'.

    Default output type 'docker' tested implicitly in other scenarios
    """
    output_str = f"output={repr(output)}," if output else ""
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                f"""\
                docker_image(
                  name="img1",
                  {output_str}
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess) -> None:
        assert result.process.argv == (
            "/dummy/docker",
            "buildx",
            "build",
            expected_output_arg,
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
        options=dict(use_buildx=True, push_on_package=DockerPushOnPackageBehavior.ALLOW),
    )


@pytest.mark.parametrize(
    ["output", "expect_error", "expected_output_arg"],
    [
        (None, False, "--output=type=docker"),
        ({"type": "registry"}, True, None),
        ({"type": "image", "push": "true"}, True, None),
    ],
)
def test_docker_output_option_when_push_on_package_error(
    rule_runner: RuleRunner,
    output: dict | None,
    expect_error: bool,
    expected_output_arg: str | None,
) -> None:
    output_str = f"output={repr(output)}," if output else ""
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                f"""\
                docker_image(
                  name="img1",
                  {output_str}
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("docker/test", target_name="img1"))
    under_test_fs = DockerPackageFieldSet.create(tgt)

    def check_build_process(result: DockerImageBuildProcess) -> None:
        assert result.process.argv == (
            "/dummy/docker",
            "buildx",
            "build",
            expected_output_arg,
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    build_process = assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process if expected_output_arg else None,
        options=dict(use_buildx=True),
    )

    def mock_execute_process(process: Process) -> FallibleProcessResult:
        assert process == build_process.process
        return FallibleProcessResult(
            exit_code=0,
            stdout=b"Successfully built abc123",
            stderr=b"",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            output_digest=EMPTY_DIGEST,
            metadata=ProcessResultMetadata(
                0,
                ProcessExecutionEnvironment(
                    environment_name=None,
                    platform=Platform.create_for_localhost().value,
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

    def mock_create_digest(request: CreateDigest) -> Digest:
        return EMPTY_DIGEST

    def mock_get_build_process_success(field_set: DockerPackageFieldSet) -> DockerImageBuildProcess:
        assert field_set == under_test_fs
        return build_process

    docker_options = _setup_docker_options(
        rule_runner, dict(use_buildx=True, push_on_package=DockerPushOnPackageBehavior.ERROR)
    )
    global_options = rule_runner.request(GlobalOptions, [])

    try:
        run_rule_with_mocks(
            build_docker_image,
            rule_args=[
                under_test_fs,
                docker_options,
                global_options,
                DockerBinary("/dummy/docker"),
                KeepSandboxes.never,
            ],
            mock_calls={
                "pants.backend.docker.goals.package_image.get_docker_image_build_process": mock_get_build_process_success,
                "pants.engine.intrinsics.execute_process": mock_execute_process,
                "pants.engine.intrinsics.create_digest": mock_create_digest,
            },
            show_warnings=False,
        )
    except DockerPushOnPackageException:
        assert expect_error
    else:
        assert not expect_error


@pytest.mark.parametrize(
    ["output", "expected_output_arg", "expected_message"],
    [
        (None, "--output=type=docker", None),
        (
            {"type": "registry"},
            "--output=type=registry",
            "Docker image docker/test:img1 will push to a registry during packaging",
        ),
        (
            {"type": "image", "push": "true"},
            "--output=type=image,push=true",
            "Docker image docker/test:img1 will push to a registry during packaging",
        ),
    ],
)
def test_docker_output_option_when_push_on_package_warn(
    rule_runner: RuleRunner,
    caplog: pytest.LogCaptureFixture,
    output: dict | None,
    expected_output_arg: str,
    expected_message: str | None,
) -> None:
    output_str = f"output={repr(output)}," if output else ""
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                f"""\
                docker_image(
                  name="img1",
                  {output_str}
                )
                """
            ),
        }
    )

    # Step 1: Validate Process construction using assert_build_process
    def check_build_process(result: DockerImageBuildProcess) -> None:
        assert result.process.argv == (
            "/dummy/docker",
            "buildx",
            "build",
            expected_output_arg,
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    build_process = assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
        options=dict(use_buildx=True),
    )

    # Step 2: Test build_docker_image with WARN behavior
    tgt = rule_runner.get_target(Address("docker/test", target_name="img1"))
    under_test_fs = DockerPackageFieldSet.create(tgt)

    def mock_get_build_process(field_set: DockerPackageFieldSet) -> DockerImageBuildProcess:
        assert field_set == under_test_fs
        return build_process

    def mock_execute_process(_process: Process) -> FallibleProcessResult:
        return FallibleProcessResult(
            exit_code=0,
            stdout=b"Successfully built abc123",
            stderr=b"",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            output_digest=EMPTY_DIGEST,
            metadata=ProcessResultMetadata(
                0,
                ProcessExecutionEnvironment(
                    environment_name=None,
                    platform=Platform.create_for_localhost().value,
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

    def mock_create_digest(_request: CreateDigest) -> Digest:
        return EMPTY_DIGEST

    docker_options = _setup_docker_options(
        rule_runner, dict(use_buildx=True, push_on_package=DockerPushOnPackageBehavior.WARN)
    )
    global_options = rule_runner.request(GlobalOptions, [])

    caplog.set_level(logging.WARNING)

    run_rule_with_mocks(
        build_docker_image,
        rule_args=[
            under_test_fs,
            docker_options,
            global_options,
            DockerBinary("/dummy/docker"),
            KeepSandboxes.never,
        ],
        mock_calls={
            "pants.backend.docker.goals.package_image.get_docker_image_build_process": mock_get_build_process,
            "pants.engine.intrinsics.execute_process": mock_execute_process,
            "pants.engine.intrinsics.create_digest": mock_create_digest,
        },
        show_warnings=False,
    )

    # Validate warning was logged
    has_message = expected_message in [
        record.message for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert has_message is (expected_message is not None)


@pytest.mark.parametrize(
    ["output", "expected_output_arg"],
    [
        (None, "--output=type=docker"),
        ({"type": "registry"}, None),
        ({"type": "image", "push": "true"}, None),
    ],
)
def test_docker_output_option_when_push_on_package_ignore(
    rule_runner: RuleRunner, output: dict | None, expected_output_arg: str | None
) -> None:
    output_str = f"output={repr(output)}," if output else ""
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                f"""\
                docker_image(
                  name="img1",
                  {output_str}
                )
                """
            ),
        }
    )
    docker_options = _setup_docker_options(
        rule_runner, dict(use_buildx=True, push_on_package=DockerPushOnPackageBehavior.IGNORE)
    )
    global_options = rule_runner.request(GlobalOptions, [])
    tgt = rule_runner.get_target(Address("docker/test", target_name="img1"))
    under_test_fs = DockerPackageFieldSet.create(tgt)

    if expected_output_arg:
        # Step 1: Validate Process construction using assert_build_process
        def check_build_process(result: DockerImageBuildProcess) -> None:
            assert result.process.argv == (
                "/dummy/docker",
                "buildx",
                "build",
                expected_output_arg,
                "--pull=False",
                "--tag",
                "img1:latest",
                "--file",
                "docker/test/Dockerfile",
                ".",
            )

        build_process = assert_build_process(
            rule_runner,
            Address("docker/test", target_name="img1"),
            build_process_assertions=check_build_process,
            options=dict(use_buildx=True),
        )

        def mock_get_build_process(field_set: DockerPackageFieldSet) -> DockerImageBuildProcess:
            assert field_set == under_test_fs
            return build_process

        def mock_execute_process(process: Process) -> FallibleProcessResult:
            assert process == build_process.process
            return FallibleProcessResult(
                exit_code=0,
                stdout=b"Successfully built abc123",
                stderr=b"",
                stdout_digest=EMPTY_FILE_DIGEST,
                stderr_digest=EMPTY_FILE_DIGEST,
                output_digest=EMPTY_DIGEST,
                metadata=ProcessResultMetadata(
                    0,
                    ProcessExecutionEnvironment(
                        environment_name=None,
                        platform=Platform.create_for_localhost().value,
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

        def mock_create_digest(_request: CreateDigest) -> Digest:
            return EMPTY_DIGEST

        mock_calls: dict[str, Callable[..., Any]] | None = {
            "pants.backend.docker.goals.package_image.get_docker_image_build_process": mock_get_build_process,
            "pants.engine.intrinsics.execute_process": mock_execute_process,
            "pants.engine.intrinsics.create_digest": mock_create_digest,
        }
    else:
        mock_calls = None

    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[
            under_test_fs,
            docker_options,
            global_options,
            DockerBinary("/dummy/docker"),
            KeepSandboxes.never,
        ],
        mock_calls=mock_calls,
        show_warnings=False,
    )

    assert result.digest == EMPTY_DIGEST
    assert len(result.artifacts) == (1 if expected_output_arg else 0)


def test_docker_output_option_raises_when_no_buildkit(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  output={"type": "image"}
                )
                """
            ),
        }
    )

    with pytest.raises(
        DockerImageOptionValueError,
        match=r"Buildx must be enabled via the Docker subsystem options in order to use this field.",
    ):
        assert_build_process(
            rule_runner,
            Address("docker/test", target_name="img1"),
        )


def test_docker_build_network_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  build_network="host",
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--network=host",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


def test_docker_build_platform_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  build_platform=["linux/amd64", "linux/arm64", "linux/arm/v7"],
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--platform=linux/amd64,linux/arm64,linux/arm/v7",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


def test_docker_build_labels_option(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "docker/test/BUILD": dedent(
                """\
                docker_image(
                  name="img1",
                  extra_build_args=[
                    "BUILD_SLAVE=tbs06",
                    "BUILD_NUMBER=13934",
                  ],
                  image_labels={
                    "build.host": "{build_args.BUILD_SLAVE}",
                    "build.job": "{build_args.BUILD_NUMBER}",
                  }
                )
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--label",
            "build.host=tbs06",
            "--label",
            "build.job=13934",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--build-arg",
            "BUILD_NUMBER=13934",
            "--build-arg",
            "BUILD_SLAVE=tbs06",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="img1"),
        build_process_assertions=check_build_process,
    )


@pytest.mark.parametrize("suggest_renames", [True, False])
@pytest.mark.parametrize(
    "context_root, copy_sources, build_context_files, expect_logged, fail_log_contains",
    [
        (
            None,
            ("src/project/bin.pex",),
            ("src.project/binary.pex", "src/project/app.py"),
            [(logging.WARNING, "Docker build failed for `docker_image` docker/test:test.")],
            [
                "suggested renames:\n\n  * src/project/bin.pex => src.project/binary.pex\n\n",
                "There are files in the Docker build context that were not referenced by ",
                "  * src/project/app.py\n\n",
            ],
        ),
        (
            "./",
            ("config.txt",),
            ("docker/test/conf/config.txt",),
            [(logging.WARNING, "Docker build failed for `docker_image` docker/test:test.")],
            [
                "suggested renames:\n\n  * config.txt => conf/config.txt\n\n",
            ],
        ),
        (
            "./",
            ("conf/config.txt",),
            (
                "docker/test/conf/config.txt",
                "src.project/binary.pex",
            ),
            [(logging.WARNING, "Docker build failed for `docker_image` docker/test:test.")],
            [
                "There are unreachable files in these directories, excluded from the build context "
                "due to `context_root` being 'docker/test':\n\n"
                "  * src.project\n\n"
                "Suggested `context_root` setting is '' in order to include all files in the "
                "build context, otherwise relocate the files to be part of the current "
                "`context_root` 'docker/test'."
            ],
        ),
        (
            "./config",
            (),
            (
                "docker/test/config/..unusal-name",
                "docker/test/config/.rc",
                "docker/test/config/.a",
                "docker/test/config/.conf.d/b",
            ),
            [(logging.WARNING, "Docker build failed for `docker_image` docker/test:test.")],
            [
                "There are files in the Docker build context that were not referenced by "
                "any `COPY` instruction (this is not an error):\n"
                "\n"
                "  * ..unusal-name\n"
                "  * .a\n"
                "  * .conf.d/b\n"
                "  * .rc\n"
            ],
        ),
    ],
)
def test_docker_build_fail_logs(
    rule_runner: RuleRunner,
    caplog,
    context_root: str | None,
    copy_sources: tuple[str, ...],
    build_context_files: tuple[str, ...],
    expect_logged: list[tuple[int, str]] | None,
    fail_log_contains: list[str],
    suggest_renames: bool,
) -> None:
    caplog.set_level(logging.INFO)
    rule_runner.write_files({"docker/test/BUILD": f"docker_image(context_root={context_root!r})"})
    build_context_files = ("docker/test/Dockerfile", *build_context_files)
    build_context_snapshot = rule_runner.make_snapshot_of_empty_files(build_context_files)
    suggest_renames_arg = (
        "--docker-suggest-renames" if suggest_renames else "--no-docker-suggest-renames"
    )
    rule_runner.set_options([suggest_renames_arg])

    # Step 1: Get the build process
    tgt = rule_runner.get_target(Address("docker/test"))
    address = Address("docker/test")

    build_context_mock = _create_build_context_mock(
        rule_runner, address, build_context_snapshot, copy_sources, (), ()
    )
    docker_options = _setup_docker_options(rule_runner, None)
    global_options = rule_runner.request(GlobalOptions, [])

    # Get image refs
    repository = address.target_name
    image_tags = tgt.get(DockerImageTagsField).value
    tags_to_use = ("latest",) if image_tags is None else image_tags
    image_refs = DockerImageRefs(
        [
            ImageRefRegistry(
                registry=None,
                repository=repository,
                tags=tuple(
                    ImageRefTag(
                        template=tag,
                        formatted=tag,
                        full_name=f"{repository}:{tag}",
                        uses_local_alias=False,
                    )
                    for tag in tags_to_use
                ),
            )
        ]
    )

    # Step 2: Create the build process with the get_docker_image_build_process rule
    under_test_fs = DockerPackageFieldSet.create(tgt)
    build_process = run_rule_with_mocks(
        get_docker_image_build_process,
        rule_args=[
            under_test_fs,
            docker_options,
            DockerBinary("/dummy/docker"),
        ],
        mock_calls={
            "pants.backend.docker.util_rules.docker_build_context.create_docker_build_context": build_context_mock,
            "pants.engine.internals.graph.resolve_target": lambda _: WrappedTarget(tgt),
            "pants.backend.docker.goals.package_image.get_image_refs": lambda _: image_refs,
        },
        show_warnings=False,
    )

    # Step 3: Test that build_docker_image handles the failure properly
    def mock_get_build_process(field_set: DockerPackageFieldSet) -> DockerImageBuildProcess:
        assert field_set == under_test_fs
        return build_process

    def mock_execute_process(_process: Process) -> FallibleProcessResult:
        # Simulate Docker build failure
        return FallibleProcessResult(
            exit_code=1,
            stdout=b"stdout",
            stderr=b"stderr",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            output_digest=EMPTY_DIGEST,
            metadata=ProcessResultMetadata(
                0,
                ProcessExecutionEnvironment(
                    environment_name=None,
                    platform=Platform.create_for_localhost().value,
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

    with pytest.raises(ProcessExecutionFailure):
        run_rule_with_mocks(
            build_docker_image,
            rule_args=[
                under_test_fs,
                docker_options,
                global_options,
                DockerBinary("/dummy/docker"),
                KeepSandboxes.never,
            ],
            mock_calls={
                "pants.backend.docker.goals.package_image.get_docker_image_build_process": mock_get_build_process,
                "pants.engine.intrinsics.execute_process": mock_execute_process,
            },
            show_warnings=False,
        )

    assert_logged(caplog, expect_logged)
    for msg in fail_log_contains:
        if suggest_renames:
            assert msg in caplog.records[0].message
        else:
            assert msg not in caplog.records[0].message


@pytest.mark.parametrize(
    "expected_target, options",
    [
        ("dev", None),
        ("prod", {"build_target_stage": "prod", "default_repository": "{name}"}),
    ],
)
def test_build_target_stage(
    rule_runner: RuleRunner, options: dict | None, expected_target: str
) -> None:
    rule_runner.write_files(
        {
            "BUILD": "docker_image(name='image', target_stage='dev')",
            "Dockerfile": dedent(
                """\
                FROM base as build
                FROM build as dev
                FROM build as prod
                """
            ),
        }
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--target",
            expected_target,
            "--tag",
            "image:latest",
            "--file",
            "Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("", target_name="image"),
        options=options,
        build_process_assertions=check_build_process,
        version_tags=("build latest", "dev latest", "prod latest"),
    )


def test_invalid_build_target_stage(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "docker_image(name='image', target_stage='bad')",
            "Dockerfile": dedent(
                """\
                FROM base as build
                FROM build as dev
                FROM build as prod
                """
            ),
        }
    )

    err = (
        r"The 'target_stage' field in `docker_image` //:image was set to 'bad', but there is no "
        r"such stage in `Dockerfile`\. Available stages: build, dev, prod\."
    )
    with pytest.raises(DockerBuildTargetStageError, match=err):
        assert_build_process(
            rule_runner,
            Address("", target_name="image"),
            version_tags=("build latest", "dev latest", "prod latest"),
        )


@pytest.mark.parametrize(
    "default_context_root, context_root, expected_context_root",
    [
        ("", None, "."),
        (".", None, "."),
        ("src", None, "src"),
        (
            "/",
            None,
            pytest.raises(
                InvalidFieldException,
                match=r"Use '' for a path relative to the build root, or '\./' for",
            ),
        ),
        (
            "/src",
            None,
            pytest.raises(
                InvalidFieldException,
                match=(
                    r"The `context_root` field in target src/docker:image must be a relative path, "
                    r"but was '/src'\. Use 'src' for a path relative to the build root, or '\./src' "
                    r"for a path relative to the BUILD file \(i\.e\. 'src/docker/src'\)\."
                ),
            ),
        ),
        ("./", None, "src/docker"),
        ("./build/context/", None, "src/docker/build/context"),
        (".build/context/", None, ".build/context"),
        ("ignored", "", "."),
        ("ignored", ".", "."),
        ("ignored", "src/context/", "src/context"),
        ("ignored", "./", "src/docker"),
        ("ignored", "src", "src"),
        ("ignored", "./build/context", "src/docker/build/context"),
    ],
)
def test_get_context_root(
    context_root: str | None, default_context_root: str, expected_context_root: str | ContextManager
) -> None:
    if isinstance(expected_context_root, str):
        raises = cast("ContextManager", no_exception())
    else:
        raises = expected_context_root

    with raises:
        docker_options = create_subsystem(
            DockerOptions,
            default_context_root=default_context_root,
        )
        address = Address("src/docker", target_name="image")
        tgt = DockerImageTarget({"context_root": context_root}, address)
        fs = DockerPackageFieldSet.create(tgt)
        actual_context_root = fs.get_context_root(docker_options.default_context_root)
        assert actual_context_root == expected_context_root


@pytest.mark.parametrize(
    "docker, expected, stdout, stderr",
    [
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "<unknown>",
            "",
            "",
        ),
        # Docker
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "0e09b442b572",
            "",
            dedent(
                """\
                Step 22/22 : LABEL job-url="https://jenkins.example.net/job/python_artefactsapi_pipeline/"
                 ---> Running in ae5c3eac5c0b
                Removing intermediate container ae5c3eac5c0b
                 ---> 0e09b442b572
                Successfully built 0e09b442b572
                Successfully tagged docker.example.net/artefactsapi/master:3.6.5
                """
            ),
        ),
        # Buildkit without step duration
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "sha256:7805a7da5f45a70bb9e47e8de09b1f5acd8f479dda06fb144c5590b9d2b86dd7",
            dedent(
                """\
                #7 [2/2] COPY testprojects.src.python.hello.main/main.pex /hello
                #7 sha256:843d0c804a7eb5ba08b0535b635d5f98a3e56bc43a3fbe7d226a8024176f00d1
                #7 DONE 0.1s

                #8 exporting to image
                #8 sha256:e8c613e07b0b7ff33893b694f7759a10d42e180f2b4dc349fb57dc6b71dcab00
                #8 exporting layers 0.0s done
                #8 writing image sha256:7805a7da5f45a70bb9e47e8de09b1f5acd8f479dda06fb144c5590b9d2b86dd7 done
                #8 naming to docker.io/library/test-example-synth:1.2.5 done
                #8 DONE 0.0s

                Use 'docker scan' to run Snyk tests against images to find vulnerabilities and learn how to fix them

                """
            ),
            "",
        ),
        # Buildkit with step duration
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "sha256:7805a7da5f45a70bb9e47e8de09b1f5acd8f479dda06fb144c5590b9d2b86dd7",
            dedent(
                """\
                #5 [2/2] RUN sleep 1
                #5 DONE 1.1s

                #6 exporting to image
                #6 exporting layers
                #6 exporting layers 0.7s done
                #6 writing image sha256:7805a7da5f45a70bb9e47e8de09b1f5acd8f479dda06fb144c5590b9d2b86dd7 0.0s done
                #6 naming to docker.io/library/my-docker-image:latest 0.1s done
                #6 DONE 1.1s
                """
            ),
            "",
        ),
        # Buildkit with containerd-snapshotter 0.12.1
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "sha256:b2b51838586286a9e544ddb31b3dbf7f6a99654d275b6e56b5f69f90138b4c0e",
            dedent(
                """\
                #9 exporting to image
                #9 exporting layers done
                #9 exporting manifest sha256:7802087e8e0801f6451d862a00a6ce8af3e4829b09bc890dea0dd2659c11b25a done
                #9 exporting config sha256:c83bed954709ba0c546d66d8f29afaac87c597f01b03fec158f3b21977c3e143 done
                #9 exporting attestation manifest sha256:399891f9628cfafaba9e034599bdd55675ac0a3bad38151ed1ebf03993669545 done
                #9 exporting manifest list sha256:b2b51838586286a9e544ddb31b3dbf7f6a99654d275b6e56b5f69f90138b4c0e done
                #9 naming to myhost.com/my_app:latest done
                #9 unpacking to myhost.com/my_app:latest done
                #9 DONE 0.0s
                """
            ),
            "",
        ),
        # Buildkit with containerd-snapshotter and cross platform 0.12.1
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "sha256:3c72de0e05bb75247e68e124e6500700f6e0597425db2ee9f08fd59ef28cea0f",
            dedent(
                """\
                #12 exporting to image
                #12 exporting layers done
                #12 exporting manifest sha256:452598369b55c27d752c45736cf26c0339612077f17df31fb0cdd79c5145d081 done
                #12 exporting config sha256:6fbcebfde0ec24b487045516c3b5ffd3f0633e756a6d5808c2e5ad75809e0ca6 done
                #12 exporting attestation manifest sha256:32fcf615e85bc9c2f606f863e8db3ca16dd77613a1e175e5972f39267e106dfb done
                #12 exporting manifest sha256:bcb911a3efbec48e3c58c2acfd38fe92321eed731c53253f0b5c883918420187 done
                #12 exporting config sha256:86e7fd0c4fa2356430d4ca188ed9e86497b8d03996ccba426d92c7e145e69990 done
                #12 exporting attestation manifest sha256:66f9e7af29dd04e6264b8e113571f7b653f1681ba124a386530145fb39ff0102 done
                #12 exporting manifest list sha256:3c72de0e05bb75247e68e124e6500700f6e0597425db2ee9f08fd59ef28cea0f done
                #12 naming to myhost.com/my_app:latest done
                #12 unpacking to myhost.com/my_app:latest done
                #12 DONE 0.0s
                """
            ),
            "",
        ),
        # Buildkit with containerd-snapshotter 0.13.1
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "sha256:d15432046b4feaebb70370fad4710151dd8f0b9741cb8bc4d20c08ed8847f17a",
            dedent(
                """\
                #13 exporting to image
                #13 exporting layers
                #13 exporting layers done
                #13 exporting manifest sha256:2f161cf7c511874936d99995adeb53c6ac2262279a606bc1b70756ca1367ceb5 done
                #13 exporting config sha256:23bf9de65f90e11ab7bb6bad0e1fb5c7eee3df2050aa902e8a53684fbd539eb9 done
                #13 exporting attestation manifest sha256:5ff8bf97d8ad78a119d95d2b887400b3482a9026192ca7fb70307dfe290c93bf 0.0s done
                #13 exporting manifest sha256:bf37d968d569812df393c7b6a48eab143066fa56a001905d9a70ec7acf3d34f4 done
                #13 exporting config sha256:7c99f317cfae97e79dc12096279b71036a60129314e670920475665d466c821f done
                #13 exporting attestation manifest sha256:4b3176781bb62e51cce743d4428e84e3559c9a23c328d6dfbfacac67f282cf70 0.0s done
                #13 exporting manifest list sha256:d15432046b4feaebb70370fad4710151dd8f0b9741cb8bc4d20c08ed8847f17a 0.0s done
                #13 naming to my-host.com/repo:latest done
                #13 unpacking to my-host.com/repo:latest done
                #13 DONE 0.1s
                """
            ),
            "",
        ),
        # Buildkit with containerd-snapshotter 0.17.1 and disabled attestations
        (
            DockerBinary("/bin/docker", "1234", is_podman=False),
            "sha256:6c3aff6414781126578b3e7b4a217682e89c616c0eac864d5b3ea7c87f1094d0",
            dedent(
                """\
                    #24 exporting to image
                    #24 exporting layers done
                    #24 preparing layers for inline cache
                    #24 preparing layers for inline cache 0.4s done
                    #24 exporting manifest sha256:6c3aff6414781126578b3e7b4a217682e89c616c0eac864d5b3ea7c87f1094d0 0.0s done
                    #24 exporting config sha256:af716170542d95134cb41b56e2dfea2c000b05b6fc4f440158ed9834ff96d1b4 0.0s done
                    #24 naming to REDACTED:latest done
                    #24 unpacking to REDACTED:latest 0.0s done
                    #24 DONE 0.5s

                    """
            ),
            "",
        ),
        # Podman
        (
            DockerBinary("/bin/podman", "abcd", is_podman=True),
            "a85499e9039a4add9712f7ea96a4aa9f0edd57d1008c6565822561ceed927eee",
            dedent(
                """\
                STEP 5/5: COPY ./ .
                COMMIT example
                --> a85499e9039a
                Successfully tagged localhost/example:latest
                a85499e9039a4add9712f7ea96a4aa9f0edd57d1008c6565822561ceed927eee
                """
            ),
            "",
        ),
    ],
)
def test_parse_image_id_from_docker_build_output(
    docker: DockerBinary, expected: str, stdout: str, stderr: str
) -> None:
    assert expected == parse_image_id_from_docker_build_output(
        docker, stdout.encode(), stderr.encode()
    )


ImageRefTest = namedtuple(
    "ImageRefTest",
    "docker_image, registries, default_repository, expect_refs, expect_error",
    defaults=({}, {}, "{name}", (), None),
)


@pytest.mark.parametrize(
    "test",
    [
        ImageRefTest(
            docker_image=dict(name="lowercase"),
            expect_refs=(
                ImageRefRegistry(
                    registry=None,
                    repository="lowercase",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="lowercase:latest",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(name="CamelCase"),
            expect_refs=(
                ImageRefRegistry(
                    registry=None,
                    repository="camelcase",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="camelcase:latest",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(image_tags=["CamelCase"]),
            expect_refs=(
                ImageRefRegistry(
                    registry=None,
                    repository="image",
                    tags=(
                        ImageRefTag(
                            template="CamelCase",
                            formatted="CamelCase",
                            uses_local_alias=False,
                            full_name="image:CamelCase",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(image_tags=["{val1}", "prefix-{val2}"]),
            expect_refs=(
                ImageRefRegistry(
                    registry=None,
                    repository="image",
                    tags=(
                        ImageRefTag(
                            template="{val1}",
                            formatted="first-value",
                            uses_local_alias=False,
                            full_name="image:first-value",
                        ),
                        ImageRefTag(
                            template="prefix-{val2}",
                            formatted="prefix-second-value",
                            uses_local_alias=False,
                            full_name="image:prefix-second-value",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(registries=["REG1.example.net"]),
            expect_refs=(
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="REG1.example.net"),
                    repository="image",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="REG1.example.net/image:latest",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(registries=["docker.io", "@private"], repository="our-the/pkg"),
            registries=dict(private={"address": "our.registry", "repository": "the/pkg"}),
            expect_refs=(
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="docker.io"),
                    repository="our-the/pkg",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="docker.io/our-the/pkg:latest",
                        ),
                    ),
                ),
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        alias="private", address="our.registry", repository="the/pkg"
                    ),
                    repository="the/pkg",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="our.registry/the/pkg:latest",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(
                registries=["docker.io", "@private"],
                repository="{parent_directory}/{default_repository}",
            ),
            registries=dict(
                private={"address": "our.registry", "repository": "{target_repository}/the/pkg"}
            ),
            expect_refs=(
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="docker.io"),
                    repository="test/image",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="docker.io/test/image:latest",
                        ),
                    ),
                ),
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        alias="private",
                        address="our.registry",
                        repository="{target_repository}/the/pkg",
                    ),
                    repository="test/image/the/pkg",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="our.registry/test/image/the/pkg:latest",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(registries=["@private"], image_tags=["prefix-{val1}"]),
            registries=dict(
                private={"address": "our.registry", "extra_image_tags": ["{val2}-suffix"]}
            ),
            expect_refs=(
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        alias="private",
                        address="our.registry",
                        extra_image_tags=("{val2}-suffix",),
                    ),
                    repository="image",
                    tags=(
                        ImageRefTag(
                            template="prefix-{val1}",
                            formatted="prefix-first-value",
                            uses_local_alias=False,
                            full_name="our.registry/image:prefix-first-value",
                        ),
                        ImageRefTag(
                            template="{val2}-suffix",
                            formatted="second-value-suffix",
                            uses_local_alias=False,
                            full_name="our.registry/image:second-value-suffix",
                        ),
                    ),
                ),
            ),
        ),
        ImageRefTest(
            docker_image=dict(repository="{default_repository}/a"),
            default_repository="{target_repository}/b",
            expect_error=pytest.raises(
                InterpolationError,
                match=(
                    r"Invalid value for the `repository` field of the `docker_image` target at "
                    r"src/test/docker:image: '\{default_repository\}/a'\.\n\n"
                    r"The formatted placeholders recurse too deep\.\n"
                    r"'\{default_repository\}/a' => '\{target_repository\}/b/a' => "
                    r"'\{default_repository\}/a/b/a'"
                ),
            ),
        ),
        ImageRefTest(
            # Test registry `use_local_alias` (#16354)
            docker_image=dict(registries=["docker.io", "@private"], repository="our-the/pkg"),
            registries=dict(
                private={
                    "address": "our.registry",
                    "repository": "the/pkg",
                    "use_local_alias": True,
                }
            ),
            expect_refs=(
                ImageRefRegistry(
                    registry=DockerRegistryOptions(address="docker.io"),
                    repository="our-the/pkg",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="docker.io/our-the/pkg:latest",
                        ),
                    ),
                ),
                ImageRefRegistry(
                    registry=DockerRegistryOptions(
                        alias="private",
                        address="our.registry",
                        repository="the/pkg",
                        use_local_alias=True,
                    ),
                    repository="the/pkg",
                    tags=(
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=False,
                            full_name="our.registry/the/pkg:latest",
                        ),
                        ImageRefTag(
                            template="latest",
                            formatted="latest",
                            uses_local_alias=True,
                            full_name="private/the/pkg:latest",
                        ),
                    ),
                ),
            ),
        ),
    ],
)
def test_image_ref_formatting(test: ImageRefTest) -> None:
    address = Address("src/test/docker", target_name=test.docker_image.pop("name", "image"))
    tgt = DockerImageTarget(test.docker_image, address)
    field_set = DockerPackageFieldSet.create(tgt)
    registries = DockerRegistries.from_dict(test.registries)
    interpolation_context = InterpolationContext.from_dict(
        {"val1": "first-value", "val2": "second-value"}
    )
    with test.expect_error or no_exception():
        image_refs = field_set.image_refs(
            test.default_repository, registries, interpolation_context
        )
        assert tuple(image_refs) == test.expect_refs


@pytest.mark.parametrize(
    "BUILD, plugin_tags, tag_flags",
    [
        (
            'docker_image(name="plugin")',
            ("1.2.3",),
            (
                "--tag",
                "plugin:latest",
                "--tag",
                "plugin:1.2.3",
            ),
        ),
        (
            'docker_image(name="plugin", image_tags=[])',
            ("1.2.3",),
            (
                "--tag",
                "plugin:1.2.3",
            ),
        ),
    ],
)
def test_docker_image_tags_from_plugin_hook(
    rule_runner: RuleRunner, BUILD: str, plugin_tags: tuple[str, ...], tag_flags: tuple[str, ...]
) -> None:
    rule_runner.write_files({"docker/test/BUILD": BUILD})

    refs = assert_get_image_refs(
        rule_runner,
        Address("docker/test", target_name="plugin"),
        plugin_tags=plugin_tags,
    )

    def check_build_process(result: DockerImageBuildProcess):
        assert result.process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            *tag_flags,
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build_process(
        rule_runner,
        Address("docker/test", target_name="plugin"),
        build_process_assertions=check_build_process,
        image_refs=refs,
    )


def test_docker_image_tags_defined(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"docker/test/BUILD": 'docker_image(name="no-tags", image_tags=[])'})

    err = "The `image_tags` field in target docker/test:no-tags must not be empty, unless"
    with pytest.raises(InvalidFieldException, match=err):
        assert_build_process(
            rule_runner,
            Address("docker/test", target_name="no-tags"),
        )


def test_docker_info_serialize() -> None:
    image_id = "abc123"
    # image refs with unique strings (i.e. not actual templates/names etc.), to make sure they're
    # ending up in the right place in the JSON
    image_refs = (
        ImageRefRegistry(
            registry=None,
            repository="repo",
            tags=(
                ImageRefTag(
                    template="repo tag1 template",
                    formatted="repo tag1 formatted",
                    uses_local_alias=False,
                    full_name="repo tag1 full name",
                ),
                ImageRefTag(
                    template="repo tag2 template",
                    formatted="repo tag2 formatted",
                    uses_local_alias=False,
                    full_name="repo tag2 full name",
                ),
            ),
        ),
        ImageRefRegistry(
            registry=DockerRegistryOptions(address="address"),
            repository="address repo",
            tags=(
                ImageRefTag(
                    template="address tag template",
                    formatted="address tag formatted",
                    uses_local_alias=False,
                    full_name="address tag full name",
                ),
            ),
        ),
        ImageRefRegistry(
            registry=DockerRegistryOptions(
                address="alias address", alias="alias", repository="alias registry repo"
            ),
            repository="alias repo",
            tags=(
                ImageRefTag(
                    template="alias tag (address) template",
                    formatted="alias tag (address) formatted",
                    uses_local_alias=False,
                    full_name="alias tag (address) full name",
                ),
                ImageRefTag(
                    template="alias tag (local alias) template",
                    formatted="alias tag (local alias) formatted",
                    uses_local_alias=True,
                    full_name="alias tag (local alias) full name",
                ),
            ),
        ),
    )

    expected = dict(
        version=1,
        image_id=image_id,
        registries=[
            dict(
                alias=None,
                address=None,
                repository="repo",
                tags=[
                    dict(
                        template="repo tag1 template",
                        tag="repo tag1 formatted",
                        uses_local_alias=False,
                        name="repo tag1 full name",
                    ),
                    dict(
                        template="repo tag2 template",
                        tag="repo tag2 formatted",
                        uses_local_alias=False,
                        name="repo tag2 full name",
                    ),
                ],
            ),
            dict(
                alias=None,
                address="address",
                repository="address repo",
                tags=[
                    dict(
                        template="address tag template",
                        tag="address tag formatted",
                        uses_local_alias=False,
                        name="address tag full name",
                    )
                ],
            ),
            dict(
                alias="alias",
                address="alias address",
                repository="alias repo",
                tags=[
                    dict(
                        template="alias tag (address) template",
                        tag="alias tag (address) formatted",
                        uses_local_alias=False,
                        name="alias tag (address) full name",
                    ),
                    dict(
                        template="alias tag (local alias) template",
                        tag="alias tag (local alias) formatted",
                        uses_local_alias=True,
                        name="alias tag (local alias) full name",
                    ),
                ],
            ),
        ],
    )

    result = DockerInfoV1.serialize(image_refs, image_id)
    assert json.loads(result) == expected


@pytest.mark.parametrize(
    ("output", "expected"),
    [({"type": "image", "push": "true"}, True), ({"type": "registry"}, True), (None, False)],
)
def test_field_set_pushes_on_package(output: dict | None, expected: bool) -> None:
    rule_runner = RuleRunner(target_types=[DockerImageTarget])
    output_str = f", output={output}" if output else ""
    rule_runner.write_files(
        {"BUILD": f"docker_image(name='image', source='Dockerfile'{output_str})"}
    )
    field_set = DockerPackageFieldSet.create(
        rule_runner.get_target(Address("", target_name="image"))
    )
    assert field_set.pushes_on_package() is expected
