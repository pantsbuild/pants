# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.docker.goals import package_image
from pants.backend.docker.subsystems import dockerfile_parser
from pants.backend.docker.target_types import DockerImageDependenciesField, DockerImageTarget
from pants.backend.docker.util_rules import docker_build_args, dockerfile
from pants.backend.docker.util_rules.dependencies import (
    InferDockerDependencies,
    infer_docker_dependencies,
)
from pants.backend.go.goals import package_binary as package_go_binary
from pants.backend.go.target_types import GoBinaryTarget
from pants.backend.python import target_types_rules as py_target_types_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.target_types import PexBinariesGeneratorTarget, PexBinary
from pants.backend.python.util_rules import pex
from pants.core.goals import package
from pants.engine.addresses import Address
from pants.engine.target import GenerateTargetsRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *dockerfile.rules(),
            *dockerfile_parser.rules(),
            *docker_build_args.rules(),
            package.find_all_packageable_targets,
            *package_image.rules(),
            *package_pex_binary.rules(),
            *package_go_binary.rules(),
            *pex.rules(),
            infer_docker_dependencies,
            py_target_types_rules.generate_targets_from_pex_binaries,
            UnionRule(GenerateTargetsRequest, py_target_types_rules.GenerateTargetsFromPexBinaries),
            QueryRule(InferredDependencies, (InferDockerDependencies,)),
        ],
        target_types=[
            DockerImageTarget,
            PexBinary,
            PexBinariesGeneratorTarget,
            GoBinaryTarget,
        ],
    )
    rule_runner.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            [
                (
                    "project/image/test/BUILD",
                    dedent(
                        """\
                        docker_image(name="base")
                        docker_image(name="image")
                        """
                    ),
                ),
                ("project/image/test/Dockerfile", "{dockerfile}"),
            ],
            id="source Dockerfile",
        ),
        pytest.param(
            [
                (
                    "project/image/test/BUILD",
                    dedent(
                        """\
                        docker_image(name="base")
                        docker_image(name="image", instructions=[{dockerfile!r}])
                        """
                    ),
                ),
            ],
            id="generate Dockerfile",
        ),
    ],
)
def test_infer_docker_dependencies(files, rule_runner: RuleRunner) -> None:
    dockerfile_content = dedent(
        """\
            ARG BASE_IMAGE=:base
            FROM $BASE_IMAGE
            ENTRYPOINT ["./entrypoint"]
            COPY project.hello.main.py/main_binary.pex /entrypoint
            COPY project.hello.main.py/cmd1_py.pex /entrypoint
            COPY project.hello.main.go/go_bin /entrypoint
        """
    )

    rule_runner.write_files(
        {
            **{
                filename: content.format(dockerfile=dockerfile_content)
                for filename, content in files
            },
            "project/hello/main/py/BUILD": dedent(
                """\
                pex_binary(name="main_binary")
                pex_binaries(name="cmds", entry_points=["cmd1.py"])
                """
            ),
            "project/hello/main/go/BUILD": dedent(
                """\
                go_binary(name="go_bin")
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("project/image/test", target_name="image"))
    inferred = rule_runner.request(
        InferredDependencies,
        [InferDockerDependencies(tgt[DockerImageDependenciesField])],
    )
    assert inferred == InferredDependencies(
        [
            Address("project/image/test", target_name="base"),
            Address("project/hello/main/py", target_name="main_binary"),
            Address("project/hello/main/py", target_name="cmds", generated_name="cmd1.py"),
            Address("project/hello/main/go", target_name="go_bin"),
        ]
    )


def test_does_not_infer_dependency_when_docker_build_arg_overwrites(
    rule_runner: RuleRunner,
) -> None:
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

    tgt = rule_runner.get_target(Address("src/downstream", target_name="image"))
    rule_runner.set_options(
        ["--docker-build-args=BASE_IMAGE=alpine:3.17.0"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    inferred = rule_runner.request(
        InferredDependencies,
        [InferDockerDependencies(tgt[DockerImageDependenciesField])],
    )
    assert inferred == InferredDependencies([])
