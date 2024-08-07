# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
import zipfile
from textwrap import dedent
from typing import Any, ContextManager

import pytest

from pants.backend.docker.goals import package_image
from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules import (
    dependencies,
    docker_binary,
    docker_build_args,
    docker_build_context,
    docker_build_env,
    dockerfile,
)
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
)
from pants.backend.docker.util_rules.docker_build_env import DockerBuildEnvironment
from pants.backend.docker.value_interpolation import DockerBuildArgsInterpolationValue
from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import PexBinary, PythonRequirementTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.shell.target_types import ShellSourcesGeneratorTarget, ShellSourceTarget
from pants.backend.shell.target_types import rules as shell_target_types_rules
from pants.core.goals import package
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget, FileTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.core.util_rules.environments import DockerEnvironmentTarget
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_SNAPSHOT, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.value_interpolation import InterpolationContext, InterpolationValue


def create_rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *core_target_types_rules(),
            *dependencies.rules(),
            *docker_binary.rules(),
            *docker_build_args.rules(),
            *docker_build_context.rules(),
            *docker_build_env.rules(),
            *dockerfile.rules(),
            *dockerfile_parser.rules(),
            *package_image.rules(),
            *package_pex_binary.rules(),
            *pex_from_targets.rules(),
            *shell_target_types_rules(),
            *target_types_rules.rules(),
            package.environment_aware_package,
            package.find_all_packageable_targets,
            QueryRule(BuiltPackage, [PexBinaryFieldSet]),
            QueryRule(DockerBuildContext, (DockerBuildContextRequest,)),
        ],
        target_types=[
            PythonRequirementTarget,
            DockerEnvironmentTarget,
            DockerImageTarget,
            FilesGeneratorTarget,
            FileTarget,
            PexBinary,
            ShellSourcesGeneratorTarget,
            ShellSourceTarget,
        ],
    )
    return rule_runner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return create_rule_runner()


def assert_build_context(
    rule_runner: RuleRunner,
    address: Address,
    *,
    build_upstream_images: bool = False,
    expected_files: list[str],
    expected_interpolation_context: dict[str, str | dict[str, str] | InterpolationValue]
    | None = None,
    expected_num_upstream_images: int = 0,
    pants_args: list[str] | None = None,
    runner_options: dict[str, Any] | None = None,
) -> DockerBuildContext:
    if runner_options is None:
        runner_options = {}
    runner_options.setdefault("env_inherit", set()).update({"PATH", "PYENV_ROOT", "HOME"})
    rule_runner.set_options(pants_args or [], **runner_options)
    context = rule_runner.request(
        DockerBuildContext,
        [
            DockerBuildContextRequest(
                address=address,
                build_upstream_images=build_upstream_images,
            )
        ],
    )

    snapshot = rule_runner.request(Snapshot, [context.digest])
    assert sorted(expected_files) == sorted(snapshot.files)
    if expected_interpolation_context is not None:
        build_args = expected_interpolation_context.get("build_args")
        if isinstance(build_args, dict):
            expected_interpolation_context["build_args"] = DockerBuildArgsInterpolationValue(
                build_args
            )

        if "pants" not in expected_interpolation_context:
            expected_interpolation_context["pants"] = context.interpolation_context["pants"]

        # Converting to `dict` to avoid the fact that FrozenDict is sensitive to the order of the keys.
        assert dict(context.interpolation_context) == dict(
            InterpolationContext.from_dict(expected_interpolation_context)
        )

    if build_upstream_images:
        assert len(context.upstream_image_ids) == expected_num_upstream_images
    return context


def test_pants_hash(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": "docker_image()",
            "test/Dockerfile": "FROM base",
        }
    )

    assert_build_context(
        rule_runner,
        Address("test"),
        expected_files=["test/Dockerfile"],
        expected_interpolation_context={
            "tags": {
                "baseimage": "latest",
                "stage0": "latest",
            },
            "build_args": {},
            "pants": {"hash": "87e90685c07ac302bbff8f9d846b4015621255f741008485fd3ce72253ce54f4"},
        },
    )


def test_file_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            # img_A -> files_A
            # img_A -> img_B
            "src/a/BUILD": dedent(
                """\
                docker_image(name="img_A", dependencies=[":files_A", "src/b:img_B"])
                files(name="files_A", sources=["files/**"])
                """
            ),
            "src/a/Dockerfile": "FROM base",
            "src/a/files/a01": "",
            "src/a/files/a02": "",
            # img_B -> files_B
            "src/b/BUILD": dedent(
                """\
                docker_image(name="img_B", dependencies=[":files_B"])
                files(name="files_B", sources=["files/**"])
                """
            ),
            "src/b/Dockerfile": "FROM base",
            "src/b/files/b01": "",
            "src/b/files/b02": "",
            # Mixed
            "src/c/BUILD": dedent(
                """\
                docker_image(name="img_C", dependencies=["src/a:files_A", "src/b:files_B"])
                """
            ),
            "src/c/Dockerfile": "FROM base",
        }
    )

    # We want files_B in build context for img_B
    assert_build_context(
        rule_runner,
        Address("src/b", target_name="img_B"),
        expected_files=["src/b/Dockerfile", "src/b/files/b01", "src/b/files/b02"],
    )

    # We want files_A in build context for img_A, but not files_B
    assert_build_context(
        rule_runner,
        Address("src/a", target_name="img_A"),
        expected_files=["src/a/Dockerfile", "src/a/files/a01", "src/a/files/a02"],
    )

    # Mixed.
    assert_build_context(
        rule_runner,
        Address("src/c", target_name="img_C"),
        expected_files=[
            "src/c/Dockerfile",
            "src/a/files/a01",
            "src/a/files/a02",
            "src/b/files/b01",
            "src/b/files/b02",
        ],
    )


def test_from_image_build_arg_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/upstream/BUILD": dedent(
                """\
                docker_image(
                  name="image",
                  repository="upstream/{name}",
                  image_tags=["1.0"],
                  instructions=["FROM alpine:3.16.1"],
                )
                """
            ),
            "src/downstream/BUILD": "docker_image(name='image')",
            "src/downstream/Dockerfile": dedent(
                """\
                ARG BASE_IMAGE=src/upstream:image
                FROM $BASE_IMAGE
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/downstream", target_name="image"),
        expected_files=["src/downstream/Dockerfile", "src.upstream/image.docker-info.json"],
        build_upstream_images=True,
        expected_interpolation_context={
            "tags": {
                "baseimage": "1.0",
                "stage0": "1.0",
            },
            "build_args": {
                "BASE_IMAGE": "upstream/image:1.0",
            },
        },
        expected_num_upstream_images=1,
    )


def test_from_image_build_arg_dependency_overwritten(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/upstream/BUILD": dedent(
                """\
                docker_image(
                  name="image",
                  repository="upstream/{name}",
                  image_tags=["1.0"],
                  instructions=["FROM alpine:3.16.1"],
                )
                """
            ),
            "src/downstream/BUILD": "docker_image(name='image')",
            "src/downstream/Dockerfile": dedent(
                """\
                ARG BASE_IMAGE=src/upstream:image
                FROM $BASE_IMAGE
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/downstream", target_name="image"),
        expected_files=["src/downstream/Dockerfile"],
        build_upstream_images=True,
        expected_interpolation_context={
            "tags": {
                "baseimage": "3.10-slim",
                "stage0": "3.10-slim",
            },
            "build_args": {
                "BASE_IMAGE": "python:3.10-slim",
            },
        },
        expected_num_upstream_images=0,
        pants_args=["--docker-build-args=BASE_IMAGE=python:3.10-slim"],
    )


def test_from_image_build_arg_not_in_repo_issue_15585(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/image/BUILD": "docker_image()",
            "test/image/Dockerfile": dedent(
                """\
                ARG PYTHON_VERSION="python:3.10.2-slim"
                FROM $PYTHON_VERSION
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("test/image", target_name="image"),
        expected_files=["test/image/Dockerfile"],
        build_upstream_images=True,
        expected_interpolation_context={
            "tags": {
                "baseimage": "3.10.2-slim",
                "stage0": "3.10.2-slim",
            },
            # PYTHON_VERSION will be treated like any other build ARG.
            "build_args": {},
        },
    )


def test_build_args_for_copy(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "testprojects/src/docker/BUILD": dedent(
                """\
            docker_image()
            file(name="file", source="file.txt")
            file(name="file_as_arg", source="file_as_arg.txt")
            """
            ),
            "testprojects/src/docker/Dockerfile": dedent(
                """\
            FROM		python:3.9

            ARG PEX_BIN="testprojects/src/python:hello"
            ARG PEX_BIN_DOTTED_PATH="testprojects.src.python/hello_dotted.pex"
            ARG FILE_AS_ARG="testprojects/src/docker/file_as_arg.txt"

            COPY		${PEX_BIN} /app/pex_bin
            COPY		$PEX_BIN_DOTTED_PATH /app/pex_var
            COPY		testprojects.src.python/hello_inline.pex /app/pex_bin_dotted_path
            COPY		${FILE_AS_ARG} /app/
            COPY		testprojects/src/docker/file.txt /app/
            """
            ),
            "testprojects/src/docker/file_as_arg.txt": "",
            "testprojects/src/docker/file.txt": "",
            "testprojects/src/python/BUILD": dedent(
                """\
            pex_binary(name="hello", entry_point="hello.py")
            pex_binary(name="hello_dotted", entry_point="hello.py")
            pex_binary(name="hello_inline", entry_point="hello.py")
            """
            ),
            "testprojects/src/python/hello.py": "",
        }
    )

    assert_build_context(
        rule_runner,
        Address("testprojects/src/docker", target_name="docker"),
        expected_files=[
            "testprojects/src/docker/Dockerfile",
            "testprojects/src/docker/file.txt",
            "testprojects/src/docker/file_as_arg.txt",
            "testprojects.src.python/hello_inline.pex",
            "testprojects.src.python/hello_dotted.pex",
            "testprojects.src.python/hello.pex",
        ],
        expected_interpolation_context={
            "build_args": {
                "FILE_AS_ARG": "testprojects/src/docker/file_as_arg.txt",
                "PEX_BIN": "testprojects.src.python/hello.pex",
            },
            "tags": {"baseimage": "3.9", "stage0": "3.9"},
        },
    )


def test_files_out_of_tree(rule_runner: RuleRunner) -> None:
    # src/a:img_A -> res/static:files
    rule_runner.write_files(
        {
            "src/a/BUILD": dedent(
                """\
                docker_image(name="img_A", dependencies=["res/static:files"])
                """
            ),
            "res/static/BUILD": dedent(
                """\
                files(name="files", sources=["!BUILD", "**/*"])
                """
            ),
            "src/a/Dockerfile": "FROM base",
            "res/static/s01": "",
            "res/static/s02": "",
            "res/static/sub/s03": "",
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/a", target_name="img_A"),
        expected_files=[
            "src/a/Dockerfile",
            "res/static/s01",
            "res/static/s02",
            "res/static/sub/s03",
        ],
    )


def test_packaged_pex_path(rule_runner: RuleRunner) -> None:
    # This test is here to ensure that we catch if there is any change in the generated path where
    # built pex binaries go, as we rely on that for dependency inference in the Dockerfile.
    rule_runner.write_files(
        {
            "src/docker/BUILD": """docker_image(dependencies=["src/python/proj/cli:bin"])""",
            "src/docker/Dockerfile": """FROM python:3.8""",
            "src/python/proj/cli/BUILD": """pex_binary(name="bin", entry_point="main.py")""",
            "src/python/proj/cli/main.py": """print("cli main")""",
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker", target_name="docker"),
        expected_files=["src/docker/Dockerfile", "src.python.proj.cli/bin.pex"],
    )


def test_packaged_pex_environment(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
              docker_environment(
                name="python_38",
                image="python:3.8-buster@sha256:bc4b9fb034a871b285bea5418cedfcaa9d2ab5590fb5fb6f0c42aaebb2e2c911",
                platform="linux_x86_64",
                python_bootstrap_search_path=["<PATH>"],
              )

              python_requirement(name="psutil", requirements=["psutil==5.9.2"])
              """
            ),
            "src/docker/BUILD": """docker_image(dependencies=["src/python/proj/cli:bin"])""",
            "src/docker/Dockerfile": """FROM python:3.8""",
            "src/python/proj/cli/BUILD": dedent(
                """
              pex_binary(
                name="bin",
                entry_point="main.py",
                environment="python_38",
                dependencies=["//:psutil"],
              )
              """
            ),
            "src/python/proj/cli/main.py": """import psutil; assert psutil.Process.is_running()""",
        }
    )

    pex_file = "src.python.proj.cli/bin.pex"
    context = assert_build_context(
        rule_runner,
        Address("src/docker", target_name="docker"),
        pants_args=["--environments-preview-names={'python_38': '//:python_38'}"],
        expected_files=["src/docker/Dockerfile", pex_file],
    )

    # Confirm that the context contains a PEX for the appropriate platform.
    rule_runner.write_digest(context.digest, path_prefix="contents")
    with zipfile.ZipFile(os.path.join(rule_runner.build_root, "contents", pex_file), "r") as zf:
        assert json.loads(zf.read("PEX-INFO"))["distributions"].keys() == {
            "psutil-5.9.2-cp37-cp37m-manylinux_2_12_x86_64.manylinux2010_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
            "psutil-5.9.2-cp38-cp38-manylinux_2_12_x86_64.manylinux2010_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        }


def test_interpolation_context_from_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/docker/BUILD": "docker_image()",
            "src/docker/Dockerfile": dedent(
                """\
                FROM python:3.8
                FROM alpine:3.16.1 as interim
                FROM interim
                FROM scratch:1-1 as output
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker"),
        expected_files=["src/docker/Dockerfile"],
        expected_interpolation_context={
            "tags": {
                "baseimage": "3.8",
                "stage0": "3.8",
                "interim": "3.16.1",
                "stage2": "latest",
                "output": "1-1",
            },
            "build_args": {},
        },
    )


def test_synthetic_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/docker/BUILD": dedent(
                """\
                docker_image(
                  instructions=[
                    "FROM python:3.8",
                    "FROM alpine:3.16.1 as interim",
                    "FROM interim",
                    "FROM scratch:1-1 as output",
                  ]
                )
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker"),
        expected_files=["src/docker/Dockerfile.docker"],
        expected_interpolation_context={
            "tags": {
                "baseimage": "3.8",
                "stage0": "3.8",
                "interim": "3.16.1",
                "stage2": "latest",
                "output": "1-1",
            },
            "build_args": {},
        },
    )


def test_shell_source_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/docker/BUILD": dedent(
                """\
                docker_image(dependencies=[":entrypoint", ":shell"])
                shell_source(name="entrypoint", source="entrypoint.sh")
                shell_sources(name="shell", sources=["scripts/**/*.sh"])
                """
            ),
            "src/docker/Dockerfile": "FROM base",
            "src/docker/entrypoint.sh": "",
            "src/docker/scripts/s01.sh": "",
            "src/docker/scripts/s02.sh": "",
            "src/docker/scripts/random.file": "",
        }
    )
    assert_build_context(
        rule_runner,
        Address("src/docker"),
        expected_files=[
            "src/docker/Dockerfile",
            "src/docker/entrypoint.sh",
            "src/docker/scripts/s01.sh",
            "src/docker/scripts/s02.sh",
        ],
    )


def test_build_arg_defaults_from_dockerfile(rule_runner: RuleRunner) -> None:
    # Test that only explicitly defined build args in the BUILD file or pants configuration use the
    # environment for its values.
    rule_runner.write_files(
        {
            "src/docker/BUILD": dedent(
                """\
                docker_image(
                  extra_build_args=[
                    "base_version",
                  ]
                )
                """
            ),
            "src/docker/Dockerfile": dedent(
                """\
                ARG base_name=python
                ARG base_version=3.8
                FROM ${base_name}:${base_version}
                ARG NO_DEF
                ENV opt=${NO_DEF}
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker"),
        runner_options={
            "env": {
                "base_name": "no-effect",
                "base_version": "3.9",
            },
        },
        expected_files=["src/docker/Dockerfile"],
        expected_interpolation_context={
            "tags": {
                "baseimage": "${base_version}",
                "stage0": "${base_version}",
            },
            "build_args": {
                # `base_name` is not listed here, as it was not an explicitly defined build arg.
                "base_version": "3.9",
            },
        },
    )


@pytest.mark.parametrize(
    "dockerfile_arg_value, extra_build_arg_value, expect",
    [
        pytest.param(None, None, no_exception(), id="No args defined"),
        pytest.param(
            None,
            "",
            pytest.raises(ExecutionError, match=r"variable 'MY_ARG' is undefined"),
            id="No default value for build arg",
        ),
        pytest.param(None, "some default value", no_exception(), id="Default value for build arg"),
        pytest.param("", None, no_exception(), id="No build arg defined, and ARG without default"),
        pytest.param(
            "",
            "",
            pytest.raises(ExecutionError, match=r"variable 'MY_ARG' is undefined"),
            id="No default value from ARG",
        ),
        pytest.param(
            "", "some default value", no_exception(), id="Default value for build arg, ARG present"
        ),
        pytest.param(
            "some default value", None, no_exception(), id="No build arg defined, only ARG"
        ),
        pytest.param("some default value", "", no_exception(), id="Default value from ARG"),
        pytest.param(
            "some default value",
            "some other default",
            no_exception(),
            id="Default value for build arg, ARG default",
        ),
    ],
)
def test_undefined_env_var_behavior(
    rule_runner: RuleRunner,
    dockerfile_arg_value: str | None,
    extra_build_arg_value: str | None,
    expect: ContextManager,
) -> None:
    dockerfile_arg = ""
    if dockerfile_arg_value is not None:
        dockerfile_arg = "ARG MY_ARG"
        if dockerfile_arg_value:
            dockerfile_arg += f"={dockerfile_arg_value}"

    extra_build_args = ""
    if extra_build_arg_value is not None:
        extra_build_args = 'extra_build_args=["MY_ARG'
        if extra_build_arg_value:
            extra_build_args += f"={extra_build_arg_value}"
        extra_build_args += '"],'

    rule_runner.write_files(
        {
            "src/docker/BUILD": dedent(
                f"""\
                docker_image(
                  {extra_build_args}
                )
                """
            ),
            "src/docker/Dockerfile": dedent(
                f"""\
                FROM python:3.8
                {dockerfile_arg}
                """
            ),
        }
    )

    with expect:
        assert_build_context(
            rule_runner,
            Address("src/docker"),
            expected_files=["src/docker/Dockerfile"],
        )


@pytest.fixture(scope="session")
def build_context() -> DockerBuildContext:
    rule_runner = create_rule_runner()
    rule_runner.write_files(
        {
            "src/docker/BUILD": dedent(
                """\
                docker_image(
                  extra_build_args=["DEF_ARG"],
                  instructions=[
                    "FROM python:3.8",
                    "ARG MY_ARG",
                    "ARG DEF_ARG=some-value",
                  ],
                )
                """
            ),
        }
    )

    return assert_build_context(
        rule_runner,
        Address("src/docker"),
        expected_files=["src/docker/Dockerfile.docker"],
    )


@pytest.mark.parametrize(
    "fmt_string, result, expectation",
    [
        pytest.param(
            "{build_args.MY_ARG}",
            None,
            pytest.raises(
                ValueError,
                match=(r"The build arg 'MY_ARG' is undefined\. Defined build args are: DEF_ARG\."),
            ),
            id="ARG_NAME",
        ),
        pytest.param(
            "{build_args.DEF_ARG}",
            "some-value",
            no_exception(),
            id="DEF_ARG",
        ),
    ],
)
def test_build_arg_behavior(
    build_context: DockerBuildContext,
    fmt_string: str,
    result: str | None,
    expectation: ContextManager,
) -> None:
    with expectation:
        assert fmt_string.format(**build_context.interpolation_context) == result


def test_create_docker_build_context() -> None:
    context = DockerBuildContext.create(
        build_args=DockerBuildArgs.from_strings("ARGNAME=value1"),
        snapshot=EMPTY_SNAPSHOT,
        build_env=DockerBuildEnvironment.create({"ENVNAME": "value2"}),
        upstream_image_ids=["def", "abc"],
        dockerfile_info=DockerfileInfo(
            address=Address("test"),
            digest=EMPTY_DIGEST,
            source="test/Dockerfile",
            build_args=DockerBuildArgs.from_strings(),
            copy_source_paths=(),
            copy_build_args=DockerBuildArgs.from_strings(),
            from_image_build_args=DockerBuildArgs.from_strings(),
            version_tags=("base latest", "stage1 1.2", "dev 2.0", "prod 2.0"),
        ),
    )
    assert list(context.build_args) == ["ARGNAME=value1"]
    assert dict(context.build_env.environment) == {"ENVNAME": "value2"}
    assert context.upstream_image_ids == ("abc", "def")
    assert context.dockerfile == "test/Dockerfile"
    assert context.stages == ("base", "dev", "prod")


def test_pex_custom_output_path_issue14031(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/test/BUILD": dedent(
                """\
                pex_binary(
                  name="test",
                  entry_point="main.py",
                  output_path="project/test.pex",
                )

                docker_image(
                  name="test-image",
                  dependencies=[":test"],
                )
                """
            ),
            "project/test/main.py": "print('Hello')",
            "project/test/Dockerfile": dedent(
                """\
                FROM python:3.8
                COPY project/test.pex .
                CMD ["./test.pex"]
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("project/test", target_name="test-image"),
        expected_files=["project/test/Dockerfile", "project/test.pex"],
    )


def test_dockerfile_instructions_issue_17571(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/docker/Dockerfile": "do not use this file",
            "src/docker/BUILD": dedent(
                """\
                docker_image(
                  source=None,
                  instructions=[
                    "FROM python:3.8",
                  ]
                )
                """
            ),
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker"),
        expected_files=["src/docker/Dockerfile.docker"],
        expected_interpolation_context={
            "tags": {
                "baseimage": "3.8",
                "stage0": "3.8",
            },
            "build_args": {},
        },
    )
