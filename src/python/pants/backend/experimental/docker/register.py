# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker import lint
from pants.backend.docker import tailor
from pants.backend.docker.target_types import DockerImage


def rules():
    return (
        *lint.rules(),
        *tailor.rules(),
    )


def target_types():
    return [
        DockerImage,
    ]
