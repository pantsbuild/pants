# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from enum import Enum


class DockerBuildEngine(Enum):
    DOCKER = "docker"
    BUILDKIT = "buildkit"
    PODMAN = "podman"


class DockerPushEngine(Enum):
    DOCKER = "docker"
    PODMAN = "podman"


class DockerRunEngine(Enum):
    DOCKER = "docker"
    PODMAN = "podman"


@dataclass(frozen=True)
class DockerEngines:
    build: DockerBuildEngine = DockerBuildEngine.DOCKER
    push: DockerPushEngine = DockerPushEngine.DOCKER
    run: DockerRunEngine = DockerRunEngine.DOCKER
