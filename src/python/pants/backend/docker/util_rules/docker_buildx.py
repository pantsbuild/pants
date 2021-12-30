# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, cast

from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@dataclass(frozen=True)
class BuildxBuilderNode:
    name: str
    endpoint: str
    status: str
    platforms: tuple[str, ...]

    @classmethod
    def parse(cls, ls_nodeline: str) -> BuildxBuilderNode:
        name, endpoint, status, platforms = (
            re.sub(r"\s+", " ", ls_nodeline).replace(", ", ",").split() + [""]
        )[:4]
        return cls(
            name=name,
            endpoint=endpoint,
            status=status,
            platforms=tuple(platforms.split(",")) if platforms else (),
        )

    @property
    def is_running(self) -> bool:
        return self.status == "running"


@dataclass(frozen=True)
class BuildxBuilder:
    name: str
    default: bool
    driver: str
    nodes: tuple[BuildxBuilderNode, ...]

    @classmethod
    def parse(cls, ls_builder: str) -> BuildxBuilder:
        ls_lines = ls_builder.split("\n")
        name, driver = re.sub(r"\s+", " ", ls_lines[0]).replace(" *", "*").split()
        return cls(
            name=name.strip("*"),
            default=name.endswith("*"),
            driver=driver,
            nodes=tuple(map(BuildxBuilderNode.parse, ls_lines[1:])),
        )

    @property
    def is_active(self) -> bool:
        return any(node.is_running for node in self.nodes)


@dataclass(frozen=True)
class DockerBuildxFeatures:
    version: str
    builders: tuple[BuildxBuilder, ...]

    @classmethod
    def create(cls, version: str, ls_output: str) -> DockerBuildxFeatures:
        return cls(
            version=version,
            builders=tuple(
                BuildxBuilder.parse(ls_builder) for ls_builder in split_builders(ls_output)
            ),
        )


@rule
async def parse_buildx_features(docker: DockerBinary) -> DockerBuildxFeatures:
    version_request = Get(
        ProcessResult,
        Process((docker.path, "buildx", "version"), description="Get Docker buildx version"),
    )
    builders_request = Get(
        ProcessResult,
        Process((docker.path, "buildx", "ls"), description="Get Docker buildx builder instances"),
    )
    version, builders = await MultiGet(version_request, builders_request)
    return DockerBuildxFeatures.create(
        version=version.stdout.decode().strip(), ls_output=builders.stdout.decode()
    )


def split_builders(ls: str) -> tuple[str, ...]:
    """Each line that starts flush left indicates the next builder."""
    # Drop the first line, being headers..
    return tuple(
        cast(
            Iterable[str],
            re.findall(r"^\w+.*\s(?:.|(?:\n\s+))*$", ls.split("\n", 1)[-1], re.MULTILINE),
        )
    )


def rules():
    return collect_rules()
