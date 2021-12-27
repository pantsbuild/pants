# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any, ContextManager

import pytest

from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo
from pants.backend.docker.subsystems.dockerfile_parser import rules as parser_rules
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs, docker_build_args
from pants.backend.docker.util_rules.docker_build_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    DockerVersionContext,
)
from pants.backend.docker.util_rules.docker_build_context import rules as context_rules
from pants.backend.docker.util_rules.docker_build_env import (
    DockerBuildEnvironment,
    docker_build_environment_vars,
)
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import PexBinary
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.shell.target_types import ShellSourcesGeneratorTarget, ShellSourceTarget
from pants.backend.shell.target_types import rules as shell_target_types_rules
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_SNAPSHOT, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner


def create_rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *context_rules(),
            *core_target_types_rules(),
            *dockerfile_rules(),
            *package_pex_binary.rules(),
            *parser_rules(),
            *pex_from_targets.rules(),
            *shell_target_types_rules(),
            *target_types_rules.rules(),
            docker_build_args,
            docker_build_environment_vars,
            QueryRule(BuiltPackage, [PexBinaryFieldSet]),
            QueryRule(DockerBuildContext, (DockerBuildContextRequest,)),
        ],
        target_types=[
            DockerImageTarget,
            FilesGeneratorTarget,
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
    expected_files: list[str],
    expected_version_context: dict[str, dict[str, str]] | None = None,
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
                build_upstream_images=False,
            )
        ],
    )

    snapshot = rule_runner.request(Snapshot, [context.digest])
    assert sorted(expected_files) == sorted(snapshot.files)
    if expected_version_context is not None:
        assert context.version_context == DockerVersionContext.from_dict(expected_version_context)
    return context


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
            "src/docker/Dockerfile": """FROM python""",
            "src/python/proj/cli/BUILD": """pex_binary(name="bin", entry_point="main.py")""",
            "src/python/proj/cli/main.py": """print("cli main")""",
        }
    )

    assert_build_context(
        rule_runner,
        Address("src/docker", target_name="docker"),
        expected_files=["src/docker/Dockerfile", "src.python.proj.cli/bin.pex"],
    )


def test_version_context_from_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/docker/BUILD": "docker_image()",
            "src/docker/Dockerfile": dedent(
                """\
                FROM python:3.8
                FROM alpine as interim
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
        expected_version_context={
            "baseimage": {"tag": "3.8"},
            "stage0": {"tag": "3.8"},
            "interim": {"tag": "latest"},
            "stage2": {"tag": "latest"},
            "output": {"tag": "1-1"},
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
                    "FROM alpine as interim",
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
        expected_version_context={
            "baseimage": {"tag": "3.8"},
            "stage0": {"tag": "3.8"},
            "interim": {"tag": "latest"},
            "stage2": {"tag": "latest"},
            "output": {"tag": "1-1"},
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
    # Test that only explicitly defined build args in the BUILD file or pants configuraiton use the
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
        expected_version_context={
            "baseimage": {"tag": "${base_version}"},
            "stage0": {"tag": "${base_version}"},
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
        assert fmt_string.format(**build_context.version_context) == result


def test_create_docker_build_context() -> None:
    context = DockerBuildContext.create(
        build_args=DockerBuildArgs.from_strings("ARGNAME=value1"),
        snapshot=EMPTY_SNAPSHOT,
        build_env=DockerBuildEnvironment.create({"ENVNAME": "value2"}),
        dockerfile_info=DockerfileInfo(
            address=Address("test"),
            digest=EMPTY_DIGEST,
            source="test/Dockerfile",
            putative_target_addresses=(),
            version_tags=("base latest", "stage1 1.2", "dev 2.0", "prod 2.0"),
            build_args=DockerBuildArgs.from_strings(),
            copy_sources=(),
        ),
    )
    assert list(context.build_args) == ["ARGNAME=value1"]
    assert dict(context.build_env.environment) == {"ENVNAME": "value2"}
    assert context.dockerfile == "test/Dockerfile"
    assert context.stages == ("base", "dev", "prod")
