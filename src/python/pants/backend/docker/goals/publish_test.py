# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

import pytest

from pants.backend.docker.goals.package_image import BuiltDockerImage, DockerFieldSet
from pants.backend.docker.goals.publish import (
    PublishDockerImageFieldSet,
    PublishDockerImageRequest,
    rules,
)
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules import docker_binary
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.backend.docker.value_interpolation import DockerInterpolationContext
from pants.core.goals.package import BuiltPackage
from pants.core.goals.publish import PublishPackages, PublishProcesses
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *rules(),
            *docker_binary.rules(),
            QueryRule(PublishProcesses, [PublishDockerImageRequest]),
            QueryRule(DockerBinary, []),
        ],
        target_types=[DockerImageTarget],
    )
    rule_runner.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    rule_runner.write_files(
        {
            "src/default/BUILD": """docker_image()""",
            "src/skip-test/BUILD": """docker_image(skip_push=True)""",
            "src/registries/BUILD": """docker_image(registries=["@inhouse1", "@inhouse2"])""",
        }
    )
    return rule_runner


def build(tgt: DockerImageTarget, options: DockerOptions):
    fs = DockerFieldSet.create(tgt)
    return (
        BuiltPackage(
            EMPTY_DIGEST,
            (
                BuiltDockerImage.create(
                    "sha256:made-up",
                    fs.image_refs(
                        options.default_repository,
                        options.registries(),
                        DockerInterpolationContext(),
                    ),
                ),
            ),
        ),
    )


def run_publish(
    rule_runner: RuleRunner, address: Address, options: dict | None = None
) -> tuple[PublishProcesses, DockerBinary]:
    opts = options or {}
    opts.setdefault("registries", {})
    opts.setdefault("default_repository", "{directory}/{name}")
    docker_options = create_subsystem(DockerOptions, **opts)
    tgt = cast(DockerImageTarget, rule_runner.get_target(address))
    fs = PublishDockerImageFieldSet.create(tgt)
    packages = build(tgt, docker_options)
    result = rule_runner.request(PublishProcesses, [fs._request(packages)])
    docker = rule_runner.request(DockerBinary, [])
    return result, docker


def assert_publish(
    publish: PublishPackages,
    expect_names: tuple[str, ...],
    expect_description: str | None,
    expect_process,
) -> None:
    assert publish.names == expect_names
    assert publish.description == expect_description
    if expect_process:
        expect_process(publish.process)
    else:
        assert publish.process is None


def process_assertion(**assertions):
    def assert_process(process):
        for attr, expected in assertions.items():
            assert getattr(process, attr) == expected

    return assert_process


def test_docker_skip_push(rule_runner: RuleRunner) -> None:
    result, _ = run_publish(rule_runner, Address("src/skip-test"))
    assert len(result) == 1
    assert_publish(
        result[0],
        ("skip-test/skip-test:latest",),
        "(by `skip_push` on src/skip-test:skip-test)",
        None,
    )


def test_docker_push_images(rule_runner: RuleRunner) -> None:
    result, docker = run_publish(rule_runner, Address("src/default"))
    assert len(result) == 1
    assert_publish(
        result[0],
        ("default/default:latest",),
        None,
        process_assertion(argv=(docker.path, "push", "default/default:latest")),
    )


def test_docker_push_registries(rule_runner: RuleRunner) -> None:
    result, docker = run_publish(
        rule_runner,
        Address("src/registries"),
        {
            "registries": {
                "inhouse1": {"address": "inhouse1.registry"},
                "inhouse2": {"address": "inhouse2.registry"},
            }
        },
    )
    assert len(result) == 2
    assert_publish(
        result[0],
        ("inhouse1.registry/registries/registries:latest",),
        None,
        process_assertion(
            argv=(
                docker.path,
                "push",
                "inhouse1.registry/registries/registries:latest",
            )
        ),
    )
    assert_publish(
        result[1],
        ("inhouse2.registry/registries/registries:latest",),
        None,
        process_assertion(
            argv=(
                docker.path,
                "push",
                "inhouse2.registry/registries/registries:latest",
            )
        ),
    )


def test_docker_push_env(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["--docker-env-vars=DOCKER_CONFIG"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        env={"DOCKER_CONFIG": "/etc/docker/custom-config"},
    )
    result, docker = run_publish(rule_runner, Address("src/default"))
    assert len(result) == 1
    assert_publish(
        result[0],
        ("default/default:latest",),
        None,
        process_assertion(
            argv=(
                docker.path,
                "push",
                "default/default:latest",
            ),
            env=FrozenDict({"DOCKER_CONFIG": "/etc/docker/custom-config"}),
        ),
    )
