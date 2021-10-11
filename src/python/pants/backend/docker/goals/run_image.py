# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import sys
from typing import cast

from pants.backend.docker.goals.package_image import BuiltDockerImage, DockerFieldSet
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunRequest
from pants.engine.rules import Get, collect_rules, rule


@rule
async def docker_image_run_request(field_set: DockerFieldSet, docker: DockerBinary) -> RunRequest:
    image = await Get(BuiltPackage, PackageFieldSet, field_set)
    return RunRequest(
        digest=image.digest,
        args=tuple(
            cast(str, arg)
            for arg in (
                docker.path,
                "run",
                "-it" if sys.stdout.isatty() else False,
                "--rm",
                cast(BuiltDockerImage, image.artifacts[0]).tags[0],
            )
            if arg
        ),
    )


def rules():
    return collect_rules()
