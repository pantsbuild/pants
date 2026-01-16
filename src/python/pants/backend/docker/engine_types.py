# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from enum import Enum


class DockerBuildEngine(Enum):
    DOCKER = "docker"
    LEGACY = "legacy"
    BUILDKIT = "buildkit"
    PODMAN = "podman"


class DockerRunEngine(Enum):
    DOCKER = "docker"
    PODMAN = "podman"
