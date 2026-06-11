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
            DEPRECATED: Use `[docker].build_engine = "podman"`,
            `[docker].push_engine = "podman"`, and `[docker].run_engine = "podman"` instead.

            If true, use Podman for builds, pushes, and runs. If false, use Docker for builds,
            pushes, and runs.
            """
        ),
        deprecation_start_version="2.33.0",
    )


def rules():
    return [
        DockerOptions.register_plugin_options(ExperimentalPodmanOptions),
    ]
