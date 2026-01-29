# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from pants.backend.docker.goals.package_image import (
    BuiltDockerImage,
    DockerImageRefs,
    DockerPackageFieldSet,
    GetImageRefsRequest,
    ImageRefRegistry,
    ImageRefTag,
)
from pants.backend.docker.goals.publish import (
    PublishDockerImageFieldSet,
    PublishDockerImageRequest,
    PublishDockerImageSkipRequest,
    check_if_skip_push,
    push_docker_images,
)
from pants.backend.docker.registries import DockerRegistryOptions
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.docker.util_rules import docker_binary
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import BuiltPackage
from pants.core.goals.publish import (
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
    CheckSkipResult,
)
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import InteractiveProcess, Process
from pants.testutil.option_util import create_subsystem
from pants.testutil.process_util import process_assertion
from pants.testutil.rule_runner import QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.frozendict import FrozenDict
from pants.util.value_interpolation import InterpolationContext


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            push_docker_images,
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
    fs = DockerPackageFieldSet.create(tgt)
    image_refs = fs.image_refs(
        options.default_repository,
        options.registries(),
        InterpolationContext(),
    )
    return (
        BuiltPackage(
            EMPTY_DIGEST,
            (
                BuiltDockerImage.create(
                    "sha256:made-up",
                    tuple(t.full_name for r in image_refs for t in r.tags),
                    "made-up.json",
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
    expect_process: Callable[[Process], None] | None,
) -> None:
    assert publish.names == expect_names
    assert publish.description == expect_description
    if expect_process:
        assert publish.process
        assert isinstance(publish.process, InteractiveProcess)
        expect_process(publish.process.process)
    else:
        assert publish.process is None


SKIP_TEST_ADDRESS = Address("src/skip-test")
REGISTRIES_ADDRESS = Address("src/registries")
DEFAULT_ADDRESS = Address("src/default")


@pytest.mark.parametrize(
    ["address", "options", "image_refs", "expected"],
    [
        pytest.param(
            DEFAULT_ADDRESS,
            {},
            None,
            CheckSkipResult.no_skip(),
            id="no_skip_conditions_early_exit",
        ),
        pytest.param(
            SKIP_TEST_ADDRESS,
            {},
            DockerImageRefs(
                [
                    ImageRefRegistry(
                        registry=None,
                        repository="skip-test/skip-test",
                        tags=(
                            ImageRefTag(
                                template="latest",
                                formatted="latest",
                                full_name="skip-test/skip-test:latest",
                                uses_local_alias=False,
                            ),
                        ),
                    ),
                ]
            ),
            CheckSkipResult.skip(
                names=["skip-test/skip-test:latest"],
                description="(by `skip_push` on src/skip-test:skip-test)",
                data={
                    "publisher": "docker",
                    "target": SKIP_TEST_ADDRESS,
                    "registries": ["<all default registries>"],
                },
            ),
            id="target_skip_push_true",
        ),
        pytest.param(
            REGISTRIES_ADDRESS,
            {
                "registries": {
                    "inhouse1": {"address": "inhouse1.registry", "skip_push": True},
                    "inhouse2": {"address": "inhouse2.registry", "skip_push": True},
                }
            },
            DockerImageRefs(
                [
                    ImageRefRegistry(
                        registry=DockerRegistryOptions(
                            address="inhouse1.registry",
                            alias="inhouse1",
                            skip_push=True,
                        ),
                        repository="registries/registries",
                        tags=(
                            ImageRefTag(
                                template="latest",
                                formatted="latest",
                                full_name="inhouse1.registry/registries/registries:latest",
                                uses_local_alias=False,
                            ),
                        ),
                    ),
                    ImageRefRegistry(
                        registry=DockerRegistryOptions(
                            address="inhouse2.registry",
                            alias="inhouse2",
                            skip_push=True,
                        ),
                        repository="registries/registries",
                        tags=(
                            ImageRefTag(
                                template="latest",
                                formatted="latest",
                                full_name="inhouse2.registry/registries/registries:latest",
                                uses_local_alias=False,
                            ),
                        ),
                    ),
                ]
            ),
            CheckSkipResult(
                [
                    PublishPackages(
                        names=("inhouse1.registry/registries/registries:latest",),
                        description="(by skip_push on @inhouse1)",
                        data=PublishOutputData.deep_freeze(
                            {
                                "publisher": "docker",
                                "target": REGISTRIES_ADDRESS,
                                "registries": ["@inhouse1", "@inhouse2"],
                            }
                        ),
                    ),
                    PublishPackages(
                        names=("inhouse2.registry/registries/registries:latest",),
                        description="(by skip_push on @inhouse2)",
                        data=PublishOutputData.deep_freeze(
                            {
                                "publisher": "docker",
                                "target": REGISTRIES_ADDRESS,
                                "registries": ["@inhouse1", "@inhouse2"],
                            }
                        ),
                    ),
                ]
            ),
            id="all_registries_skip_push_true",
        ),
        pytest.param(
            REGISTRIES_ADDRESS,
            {
                "registries": {
                    "inhouse1": {"address": "inhouse1.registry", "skip_push": True},
                    "inhouse2": {"address": "inhouse2.registry"},
                }
            },
            DockerImageRefs(
                [
                    ImageRefRegistry(
                        registry=DockerRegistryOptions(
                            address="inhouse1.registry",
                            alias="inhouse1",
                            skip_push=True,
                        ),
                        repository="registries/registries",
                        tags=(
                            ImageRefTag(
                                template="latest",
                                formatted="latest",
                                full_name="inhouse1.registry/registries/registries:latest",
                                uses_local_alias=False,
                            ),
                        ),
                    ),
                    ImageRefRegistry(
                        registry=DockerRegistryOptions(
                            address="inhouse2.registry",
                            alias="inhouse2",
                            skip_push=False,
                        ),
                        repository="registries/registries",
                        tags=(
                            ImageRefTag(
                                template="latest",
                                formatted="latest",
                                full_name="inhouse2.registry/registries/registries:latest",
                                uses_local_alias=False,
                            ),
                        ),
                    ),
                ]
            ),
            CheckSkipResult.no_skip(),
            id="mixed_registries_should_not_skip",
        ),
    ],
)
def test_check_if_skip_push(
    rule_runner: RuleRunner,
    address: Address,
    options: dict,
    image_refs: DockerImageRefs | None,
    expected: CheckSkipResult,
) -> None:
    opts = options or {}
    opts.setdefault("registries", {})
    opts.setdefault("default_repository", "{directory}/{name}")
    docker_options = create_subsystem(DockerOptions, **opts)
    tgt = cast(DockerImageTarget, rule_runner.get_target(address))
    package_fs = DockerPackageFieldSet.create(tgt)
    publish_fs = PublishDockerImageFieldSet.create(tgt)

    def mock_get_image_refs(request: GetImageRefsRequest) -> DockerImageRefs:
        assert request.field_set == package_fs
        assert request.build_upstream_images is False
        return cast(DockerImageRefs, image_refs)

    mock_calls = (
        {"pants.backend.docker.goals.package_image.get_image_refs": mock_get_image_refs}
        if image_refs
        else None
    )
    result = run_rule_with_mocks(
        check_if_skip_push,
        rule_args=[
            PublishDockerImageSkipRequest(publish_fs=publish_fs, package_fs=package_fs),
            docker_options,
        ],
        mock_calls=mock_calls,
    )
    assert result == expected


def test_docker_skip_push(rule_runner: RuleRunner) -> None:
    result, _ = run_publish(rule_runner, SKIP_TEST_ADDRESS)
    assert len(result) == 1
    assert_publish(
        result[0],
        ("skip-test/skip-test:latest",),
        "(by `skip_push` on src/skip-test:skip-test)",
        None,
    )


def test_docker_push_images(rule_runner: RuleRunner) -> None:
    result, docker = run_publish(rule_runner, DEFAULT_ADDRESS)
    assert len(result) == 1
    assert_publish(
        result[0],
        ("default/default:latest",),
        None,
        process_assertion(argv=(docker.path, "push", "default/default:latest")),
    )


def test_docker_push_registries(rule_runner: RuleRunner) -> None:
    registries = {
        "inhouse1": {"address": "inhouse1.registry"},
        "inhouse2": {"address": "inhouse2.registry"},
    }
    rule_runner.set_options(
        [f"--docker-registries={registries}"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    result, docker = run_publish(
        rule_runner,
        REGISTRIES_ADDRESS,
        {
            "registries": registries,
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


def test_docker_skip_push_registries(rule_runner: RuleRunner) -> None:
    registries = {
        "inhouse1": {"address": "inhouse1.registry"},
        "inhouse2": {"address": "inhouse2.registry", "skip_push": True},
    }
    rule_runner.set_options(
        [f"--docker-registries={registries}"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    result, docker = run_publish(
        rule_runner,
        REGISTRIES_ADDRESS,
        {
            "registries": registries,
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
        "(by `skip_push` on registry @inhouse2)",
        None,
    )


def test_docker_push_env(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["--docker-env-vars=DOCKER_CONFIG"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        env={"DOCKER_CONFIG": "/etc/docker/custom-config"},
    )
    result, docker = run_publish(rule_runner, DEFAULT_ADDRESS)
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
