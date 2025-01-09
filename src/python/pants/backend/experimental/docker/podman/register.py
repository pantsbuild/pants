# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.option.option_types import BoolOption
from pants.util.strutil import softwrap


class ExperimentalPodmanOptions:
    experimental_enable_podman = BoolOption(
        default=True,
        help=softwrap(
            """
            Allow support for podman when available.
            """
        ),
    )


def rules():
    return [
        DockerOptions.register_plugin_options(ExperimentalPodmanOptions),
    ]
