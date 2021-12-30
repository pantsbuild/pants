# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.docker.util_rules.docker_buildx import (
    BuildxBuilder,
    BuildxBuilderNode,
    DockerBuildxFeatures,
    split_builders,
)

ls_output = """\
NAME/NODE       DRIVER/ENDPOINT             STATUS   PLATFORMS
test *          docker-container
  test0         unix:///var/run/docker.sock stopped
  other         desktop-linux               inactive
desktop-linux   docker
  desktop-linux desktop-linux               running  linux/amd64, linux/arm64, linux/riscv64, linux/ppc64le, linux/s390x, linux/386, linux/arm/v7, linux/arm/v6
default         docker
  default       default                     running  linux/amd64, linux/arm64, linux/riscv64, linux/ppc64le, linux/s390x, linux/386, linux/arm/v7, linux/arm/v6
"""
ls_output_lines = ls_output.split("\n")


@pytest.mark.parametrize(
    "ls, builders",
    [
        (
            ls_output,
            (
                BuildxBuilder(
                    name="test",
                    default=True,
                    driver="docker-container",
                    nodes=(
                        BuildxBuilderNode(
                            name="test0",
                            endpoint="unix:///var/run/docker.sock",
                            status="stopped",
                            platforms=(),
                        ),
                        BuildxBuilderNode(
                            name="other", endpoint="desktop-linux", status="inactive", platforms=()
                        ),
                    ),
                ),
                BuildxBuilder(
                    name="desktop-linux",
                    default=False,
                    driver="docker",
                    nodes=(
                        BuildxBuilderNode(
                            name="desktop-linux",
                            endpoint="desktop-linux",
                            status="running",
                            platforms=(
                                "linux/amd64",
                                "linux/arm64",
                                "linux/riscv64",
                                "linux/ppc64le",
                                "linux/s390x",
                                "linux/386",
                                "linux/arm/v7",
                                "linux/arm/v6",
                            ),
                        ),
                    ),
                ),
                BuildxBuilder(
                    name="default",
                    default=False,
                    driver="docker",
                    nodes=(
                        BuildxBuilderNode(
                            name="default",
                            endpoint="default",
                            status="running",
                            platforms=(
                                "linux/amd64",
                                "linux/arm64",
                                "linux/riscv64",
                                "linux/ppc64le",
                                "linux/s390x",
                                "linux/386",
                                "linux/arm/v7",
                                "linux/arm/v6",
                            ),
                        ),
                    ),
                ),
            ),
        )
    ],
)
def test_parse_ls(ls: str, builders: tuple[BuildxBuilder, ...]) -> None:
    buildx = DockerBuildxFeatures.create(
        version="github.com/docker/buildx v0.7.1 05846896d149da05f3d6fd1e7770da187b52a247",
        ls_output=ls,
    )
    assert buildx.builders == builders


@pytest.mark.parametrize(
    "ls, builders",
    [
        (
            ls_output,
            (
                "\n".join(ls_output_lines[1:4]),
                "\n".join(ls_output_lines[4:6]),
                "\n".join(ls_output_lines[6:8]),
            ),
        ),
    ],
)
def test_split_builders(ls: str, builders: tuple[str, ...]) -> None:
    assert split_builders(ls) == builders


def test_builder_parse() -> None:
    builder_line = "test *          docker-container"
    assert BuildxBuilder.parse(builder_line) == BuildxBuilder(
        name="test", default=True, driver="docker-container", nodes=()
    )


def test_node_parse() -> None:
    node_line = "  test0         unix:///var/run/docker.sock running linux/amd64, linux/arm64, linux/riscv64, linux/ppc64le, linux/s390x, linux/386, linux/mips64le, linux/mips64, linux/arm/v7, linux/arm/v6"
    assert BuildxBuilderNode.parse(node_line) == BuildxBuilderNode(
        name="test0",
        endpoint="unix:///var/run/docker.sock",
        status="running",
        platforms=(
            "linux/amd64",
            "linux/arm64",
            "linux/riscv64",
            "linux/ppc64le",
            "linux/s390x",
            "linux/386",
            "linux/mips64le",
            "linux/mips64",
            "linux/arm/v7",
            "linux/arm/v6",
        ),
    )
