# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.engine.platform import Platform


@dataclass(frozen=True)
class DockerResolveImageRequest:
    image_name: str
    platform: str


@dataclass(frozen=True)
class DockerResolveImageResult:
    image_id: str
