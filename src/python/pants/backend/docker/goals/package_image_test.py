# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os.path
from textwrap import dedent
from typing import Callable, ContextManager, cast

import pytest

from pants.backend.docker.goals.package_image import (
    DockerBuildTargetStageError,
    DockerFieldSet,
    DockerImageTagValueError,
    DockerRepositoryNameError,
    build_docker_image,
    parse_image_id_from_docker_build_output,
    rules,
)
from pants.backend.docker.registries import DockerRegistries
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo
from pants.backend.docker.target_types import DockerImageTarget
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
from pants.backend.docker.value_interpolation import DockerInterpolationContext
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST, EMPTY_SNAPSHOT, Snapshot
from pants.engine.platform import Platform
from pants.engine.process import (
    FallibleProcessResult,
    Process,
    ProcessExecutionFailure,
    ProcessResultMetadata,
)
from pants.engine.target import InvalidFieldException, WrappedTarget
from pants.option.global_options import GlobalOptions, ProcessCleanupOption
from pants.testutil.option_util import create_subsystem
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.testutil.rule_runner import (
    MockGet,
    QueryRule,
    RuleRunner,
    engine_error,
    run_rule_with_mocks,
)
from pants.util.frozendict import FrozenDict


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
) -> None:
    tgt = rule_runner.get_target(address)

    def build_context_mock(request: DockerBuildContextRequest) -> DockerBuildContext:
        return DockerBuildContext.create(
            snapshot=build_context_snapshot,
            dockerfile_info=DockerfileInfo(
                request.address,
                digest=EMPTY_DIGEST,
                source=os.path.join(address.spec_path, "Dockerfile"),
                copy_sources=copy_sources,
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
            platform=Platform.current,
            metadata=ProcessResultMetadata(0, "ran_locally", 0),
        )

    if options:
        opts = options or {}
        opts.setdefault("registries", {})
        opts.setdefault("default_repository", "{name}")
        opts.setdefault("default_context_root", "")
        opts.setdefault("build_args", [])
        opts.setdefault("build_target_stage", None)
        opts.setdefault("build_verbose", False)
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
            DockerFieldSet.create(tgt),
            docker_options,
            global_options,
            DockerBinary("/dummy/docker"),
            ProcessCleanupOption(True),
        ],
        mock_gets=[
            MockGet(
                output_type=DockerBuildContext,
                input_type=DockerBuildContextRequest,
                mock=build_context_mock,
            ),
            MockGet(
                output_type=WrappedTarget,
                input_type=Address,
                mock=lambda _: WrappedTarget(tgt),
            ),
            MockGet(
                output_type=FallibleProcessResult,
                input_type=Process,
                mock=run_process_mock,
            ),
        ],
    )

    assert result.digest == EMPTY_DIGEST
    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath is None

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
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="test2"),
        "Built docker image: test2:1.2.3",
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
    )

    err1 = (
        r"Invalid value for the `repository` field of the `docker_image` target at "
        r"docker/test:err1: '{bad_template}'\.\n\nThe placeholder 'bad_template' is unknown\. "
        r"Try with one of: build_args, directory, name, pants, parent_directory, tags\."
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
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="alias1"),
        "Built docker image: myregistry1domain:port/alias1:1.2.3",
        options=options,
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
    )
    assert_build(
        rule_runner,
        Address("docker/test", target_name="def"),
        "Built docker image: myregistry2domain:port/def:1.2.3",
        options=options,
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
    )


def test_dynamic_image_version(rule_runner: RuleRunner) -> None:
    interpolation_context = DockerInterpolationContext.from_dict(
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
        fs = DockerFieldSet.create(tgt)
        tags = fs.image_refs(
            "image",
            DockerRegistries.from_dict({}),
            interpolation_context,
        )
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
            }
        )

    assert_build(
        rule_runner,
        Address("docker/test", target_name="env1"),
        process_assertions=check_docker_proc,
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
            (
                "src.project/binary.pex",
                "src/project/app.py",
            ),
            [(logging.WARNING, "Docker build failed for `docker_image` docker/test:test.")],
            [
                "suggested renames:\n\n  * src/project/bin.pex => src.project/binary.pex\n\n",
                "There are additional files",
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
                        "Docker build failed for `docker_image` docker/test:test. The "
                        "docker/test/Dockerfile have `COPY` instructions where the source files "
                        "may not have been found in the Docker build context.\n"
                        "\n"
                        "There are additional files in the Docker build context that were not "
                        "referenced by any `COPY` instruction (this is not an error):\n"
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
            engine_error(
                InvalidFieldException,
                contains=("Use '' for a path relative to the build root, or './' for"),
            ),
        ),
        (
            "/src",
            None,
            engine_error(
                InvalidFieldException,
                contains=(
                    "The `context_root` field in target src/docker:image must be a relative path, but was "
                    "'/src'. Use 'src' for a path relative to the build root, or './src' for a path "
                    "relative to the BUILD file (i.e. 'src/docker/src')."
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
        expected_context_root = ""

    with raises:
        docker_options = create_subsystem(
            DockerOptions,
            default_context_root=default_context_root,
        )
        address = Address("src/docker", target_name="image")
        tgt = DockerImageTarget({"context_root": context_root}, address)
        fs = DockerFieldSet.create(tgt)
        actual_context_root = fs.get_context_root(docker_options.default_context_root)
        if expected_context_root:
            assert actual_context_root == expected_context_root


@pytest.mark.parametrize(
    "expected, stdout, stderr",
    [
        (
            "<unknown>",
            "",
            "",
        ),
        (
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
        (
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
    ],
)
def test_parse_image_id_from_docker_build_output(expected: str, stdout: str, stderr: str) -> None:
    assert expected == parse_image_id_from_docker_build_output(stdout.encode(), stderr.encode())
