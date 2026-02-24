# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from enum import Enum
from dataclasses import dataclass


class DockerBuildEngine(Enum):
    DOCKER = "docker"
    BUILDKIT = "buildkit"
    PODMAN = "podman"


class DockerRunEngine(Enum):
    DOCKER = "docker"
    PODMAN = "podman"


@dataclass(frozen=True)
class DockerEngines:
    build: DockerBuildEngine = DockerBuildEngine.DOCKER
    run: DockerRunEngine = DockerRunEngine.DOCKER
