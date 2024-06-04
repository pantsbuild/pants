# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os.path
from collections import namedtuple
from textwrap import dedent
from typing import Callable, ContextManager, cast

import pytest

from pants.backend.docker.goals.package_image import (
    DockerBuildTargetStageError,
    DockerImageOptionValueError,
    DockerImageTagValueError,
    DockerInfoV1,
    DockerPackageFieldSet,
    DockerRepositoryNameError,
    ImageRefRegistry,
    ImageRefTag,
    build_docker_image,
    parse_image_id_from_docker_build_output,
    rules,
)
from pants.backend.docker.registries import DockerRegistries, DockerRegistryOptions
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo
from pants.backend.docker.target_types import (
    DockerImageTags,
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
from pants.engine.target import InvalidFieldException, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import GlobalOptions, KeepSandboxes
from pants.testutil.option_util import create_subsystem
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
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


def assert_build(
    rule_runner: RuleRunner,
    address: Address,
    *extra_log_lines: str,
    options: dict | None = None,
    process_assertions: Callable[[Process], None] | None = None,
    exit_code: int = 0,
    copy_sources: tuple[str, ...] = (),
    build_context_snapshot: Snapshot = EMPTY_SNAPSHOT,
    version_tags: tuple[str, ...] = (),
    plugin_tags: tuple[str, ...] = (),
    expected_registries_metadata: None | list = None,
) -> None:
    tgt = rule_runner.get_target(address)
    metadata_file_path: list[str] = []
    metadata_file_contents: list[bytes] = []

    def build_context_mock(request: DockerBuildContextRequest) -> DockerBuildContext:
        return DockerBuildContext.create(
            snapshot=build_context_snapshot,
            upstream_image_ids=[],
            dockerfile_info=DockerfileInfo(
                request.address,
                digest=EMPTY_DIGEST,
                source=os.path.join(address.spec_path, "Dockerfile"),
                copy_source_paths=copy_sources,
                version_tags=version_tags,
            ),
            build_args=rule_runner.request(DockerBuildArgs, [DockerBuildArgsRequest(tgt)]),
            build_env=rule_runner.request(
                DockerBuildEnvironment, [DockerBuildEnvironmentRequest(tgt)]
            ),
        )

    def run_process_mock(process: Process) -> FallibleProcessResult:
        if process_assertions:
            process_assertions(process)

        return FallibleProcessResult(
            exit_code=exit_code,
            stdout=b"stdout",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr=b"stderr",
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
                ),
                "ran_locally",
                0,
            ),
        )

    def mock_get_info_file(request: CreateDigest) -> Digest:
        assert len(request) == 1
        assert isinstance(request[0], FileContent)
        metadata_file_path.append(request[0].path)
        metadata_file_contents.append(request[0].content)
        return EMPTY_DIGEST

    if options:
        opts = options or {}
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

        docker_options = create_subsystem(
            DockerOptions,
            **opts,
        )
    else:
        docker_options = rule_runner.request(DockerOptions, [])

    global_options = rule_runner.request(GlobalOptions, [])

    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[
            DockerPackageFieldSet.create(tgt),
            docker_options,
            global_options,
            DockerBinary("/dummy/docker"),
            KeepSandboxes.never,
            UnionMembership.from_rules(
                [UnionRule(DockerImageTagsRequest, DockerImageTagsRequestPlugin)]
            ),
        ],
        mock_gets=[
            MockGet(
                output_type=DockerBuildContext,
                input_types=(DockerBuildContextRequest,),
                mock=build_context_mock,
            ),
            MockGet(
                output_type=WrappedTarget,
                input_types=(WrappedTargetRequest,),
                mock=lambda _: WrappedTarget(tgt),
            ),
            MockGet(
                output_type=DockerImageTags,
                input_types=(DockerImageTagsRequestPlugin,),
                mock=lambda _: DockerImageTags(plugin_tags),
            ),
            MockGet(
                output_type=FallibleProcessResult,
                input_types=(Process,),
                mock=run_process_mock,
            ),
            MockGet(
                output_type=Digest,
                input_types=(CreateDigest,),
                mock=mock_get_info_file,
            ),
        ],
    )

    assert result.digest == EMPTY_DIGEST
    assert len(result.artifacts) == 1
    assert len(metadata_file_path) == len(metadata_file_contents) == 1
    assert result.artifacts[0].relpath == metadata_file_path[0]

    metadata = json.loads(metadata_file_contents[0])
    # basic checks that we can always do
    assert metadata["version"] == 1
    assert metadata["image_id"] == "<unknown>"
    assert isinstance(metadata["registries"], list)
    # detailed checks, if the test opts in
    if expected_registries_metadata is not None:
        assert metadata["registries"] == expected_registries_metadata

    for log_line in extra_log_lines:
        assert log_line in result.artifacts[0].extra_log_lines


def test_build_docker_image(rule_runner: RuleRunner) -> None:
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="test1"),
        "Built docker image: test/test1:1.2.3",
        expected_registries_metadata=[
            dict(
                alias=None,
                address=None,
                repository="test/test1",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="test/test1:1.2.3",
                    )
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test2"),
        "Built docker image: test2:1.2.3",
        expected_registries_metadata=[
            dict(
                alias=None,
                address=None,
                repository="test2",
                tags=[
                    dict(template="1.2.3", tag="1.2.3", uses_local_alias=False, name="test2:1.2.3")
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test3"),
        "Built docker image: docker/test/test3:1.2.3",
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test4"),
        "Built docker image: test/four/test-four:1.2.3",
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test5"),
        (
            "Built docker images: \n"
            "  * test/test5:latest\n"
            "  * test/test5:alpha-1.0\n"
            "  * test/test5:alpha-1"
        ),
        options=dict(default_repository="{directory}/{name}"),
        expected_registries_metadata=[
            dict(
                alias=None,
                address=None,
                repository="test/test5",
                tags=[
                    dict(
                        template="alpha-1",
                        tag="alpha-1",
                        uses_local_alias=False,
                        name="test/test5:alpha-1",
                    ),
                    dict(
                        template="alpha-1.0",
                        tag="alpha-1.0",
                        uses_local_alias=False,
                        name="test/test5:alpha-1.0",
                    ),
                    dict(
                        template="latest",
                        tag="latest",
                        uses_local_alias=False,
                        name="test/test5:latest",
                    ),
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test6"),
        "Built docker image: xyz/docker/test/test6:1.2.3",
    )

    err1 = (
        r"Invalid value for the `repository` field of the `docker_image` target at "
        r"docker/test:err1: '{bad_template}'\.\n\nThe placeholder 'bad_template' is unknown\. "
        r"Try with one of: build_args, default_repository, directory, full_directory, name, "
        r"pants, parent_directory, tags, target_repository\."
    )
    with pytest.raises(DockerRepositoryNameError, match=err1):
        assert_build(
            rule_runner,
            Address("docker/test", target_name="err1"),
        )


def test_build_image_with_registries(rule_runner: RuleRunner) -> None:
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
            "reg2": {"address": "myregistry2domain:port", "default": "true"},
            "extra": {"address": "extra", "extra_image_tags": ["latest"]},
        },
    }

    assert_build(
        rule_runner,
        Address("docker/test", target_name="addr1"),
        "Built docker image: myregistry1domain:port/addr1:1.2.3",
        options=options,
        expected_registries_metadata=[
            dict(
                alias="reg1",
                address="myregistry1domain:port",
                repository="addr1",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="myregistry1domain:port/addr1:1.2.3",
                    )
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="addr2"),
        "Built docker image: myregistry2domain:port/addr2:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="addr3"),
        "Built docker image: myregistry3domain:port/addr3:1.2.3",
        options=options,
        expected_registries_metadata=[
            dict(
                alias=None,
                address="myregistry3domain:port",
                repository="addr3",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="myregistry3domain:port/addr3:1.2.3",
                    )
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="alias1"),
        "Built docker image: myregistry1domain:port/alias1:1.2.3",
        options=options,
        expected_registries_metadata=[
            dict(
                alias="reg1",
                address="myregistry1domain:port",
                repository="alias1",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="myregistry1domain:port/alias1:1.2.3",
                    )
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="alias2"),
        "Built docker image: myregistry2domain:port/alias2:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="alias3"),
        "Built docker image: reg3/alias3:1.2.3",
        options=options,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="unreg"),
        "Built docker image: unreg:1.2.3",
        options=options,
        expected_registries_metadata=[
            dict(
                alias=None,
                address=None,
                repository="unreg",
                tags=[
                    dict(template="1.2.3", tag="1.2.3", uses_local_alias=False, name="unreg:1.2.3")
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="def"),
        "Built docker image: myregistry2domain:port/def:1.2.3",
        options=options,
        expected_registries_metadata=[
            dict(
                alias="reg2",
                address="myregistry2domain:port",
                repository="def",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="myregistry2domain:port/def:1.2.3",
                    )
                ],
            )
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="multi"),
        (
            "Built docker images: \n"
            "  * myregistry2domain:port/multi:1.2.3\n"
            "  * myregistry1domain:port/multi:1.2.3"
        ),
        options=options,
        expected_registries_metadata=[
            dict(
                alias="reg1",
                address="myregistry1domain:port",
                repository="multi",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="myregistry1domain:port/multi:1.2.3",
                    )
                ],
            ),
            dict(
                alias="reg2",
                address="myregistry2domain:port",
                repository="multi",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="myregistry2domain:port/multi:1.2.3",
                    )
                ],
            ),
        ],
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="extra_tags"),
        (
            "Built docker images: \n"
            "  * myregistry1domain:port/extra_tags:1.2.3\n"
            "  * extra/extra_tags:1.2.3\n"
            "  * extra/extra_tags:latest"
        ),
        options=options,
        expected_registries_metadata=[
            dict(
                alias="extra",
                address="extra",
                repository="extra_tags",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="extra/extra_tags:1.2.3",
                    ),
                    dict(
                        template="latest",
                        tag="latest",
                        uses_local_alias=False,
                        name="extra/extra_tags:latest",
                    ),
                ],
            ),
            dict(
                alias="reg1",
                address="myregistry1domain:port",
                repository="extra_tags",
                tags=[
                    dict(
                        template="1.2.3",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="myregistry1domain:port/extra_tags:1.2.3",
                    )
                ],
            ),
        ],
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

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--tag",
            "env1:1.2.3",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )
        assert process.env == FrozenDict(
            {
                "INHERIT": "from Pants env",
                "VAR": "value",
                "__UPSTREAM_IMAGE_IDS": "",
            }
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="env1"),
        process_assertions=check_docker_proc,
    )


def test_docker_build_pull(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"docker/test/BUILD": 'docker_image(name="args1", pull=True)'})

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "--pull=True",
            "--tag",
            "args1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="args1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    def check_docker_proc_no_squash(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            "--tag",
            "args2:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="args1"),
        process_assertions=check_docker_proc,
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="args2"),
        process_assertions=check_docker_proc_no_squash,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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
        assert process.env == FrozenDict(
            {
                "INHERIT": "from Pants env",
                "__UPSTREAM_IMAGE_IDS": "",
            }
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="args1"),
        process_assertions=check_docker_proc,
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="ver1"),
        "Built docker image: ver1:1.2.3",
        expected_registries_metadata=[
            dict(
                alias=None,
                address=None,
                repository="ver1",
                tags=[
                    dict(
                        template="{build_args.VERSION}",
                        tag="1.2.3",
                        uses_local_alias=False,
                        name="ver1:1.2.3",
                    )
                ],
            )
        ],
    )


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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="image"),
        "Built docker image: test/image:latest",
    )


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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

        assert process.env == FrozenDict(
            {
                "FROM_ENV": "env value",
                "__UPSTREAM_IMAGE_IDS": "",
            }
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
        options=dict(use_buildx=True),
    )


def test_docker_output_option(rule_runner: RuleRunner) -> None:
    """Testing non-default output type 'image'.

    Default output type 'docker' tested implicitly in other scenarios
    """
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

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "buildx",
            "build",
            "--output=type=image",
            "--pull=False",
            "--tag",
            "img1:latest",
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
        options=dict(use_buildx=True),
    )


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
        assert_build(
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("docker/test", target_name="img1"),
        process_assertions=check_docker_proc,
    )


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
            [
                (
                    logging.WARNING,
                    (
                        "Docker build failed for `docker_image` docker/test:test. "
                        "There are files in the Docker build context that were not referenced by "
                        "any `COPY` instruction (this is not an error):\n"
                        "\n"
                        "  * ..unusal-name\n"
                        "  * .a\n"
                        "  * .conf.d/b\n"
                        "  * .rc\n"
                    ),
                )
            ],
            [],
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
) -> None:
    caplog.set_level(logging.INFO)
    rule_runner.write_files({"docker/test/BUILD": f"docker_image(context_root={context_root!r})"})
    build_context_files = ("docker/test/Dockerfile", *build_context_files)
    build_context_snapshot = rule_runner.make_snapshot_of_empty_files(build_context_files)
    with pytest.raises(ProcessExecutionFailure):
        assert_build(
            rule_runner,
            Address("docker/test"),
            exit_code=1,
            copy_sources=copy_sources,
            build_context_snapshot=build_context_snapshot,
        )

    assert_logged(caplog, expect_logged)
    for msg in fail_log_contains:
        assert msg in caplog.records[0].message


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

    def check_docker_proc(process: Process):
        assert process.argv == (
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

    assert_build(
        rule_runner,
        Address("", target_name="image"),
        options=options,
        process_assertions=check_docker_proc,
        version_tags=("build latest", "dev latest", "prod latest"),
        expected_registries_metadata=[
            dict(
                address=None,
                alias=None,
                repository="image",
                tags=[
                    dict(
                        template="latest", tag="latest", uses_local_alias=False, name="image:latest"
                    )
                ],
            )
        ],
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
        assert_build(
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
        # Buildkit
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
        # Buildkit on Windows ??? Buildkit version?
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

    def check_docker_proc(process: Process):
        assert process.argv == (
            "/dummy/docker",
            "build",
            "--pull=False",
            *tag_flags,
            "--file",
            "docker/test/Dockerfile",
            ".",
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="plugin"),
        process_assertions=check_docker_proc,
        plugin_tags=plugin_tags,
    )


def test_docker_image_tags_defined(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"docker/test/BUILD": 'docker_image(name="no-tags", image_tags=[])'})

    err = "The `image_tags` field in target docker/test:no-tags must not be empty, unless"
    with pytest.raises(InvalidFieldException, match=err):
        assert_build(
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
