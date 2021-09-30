# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.docker.registries import DockerRegistries
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_method


class DockerOptions(Subsystem):
    options_scope = "docker"
    help = "Options for interacting with Docker."

    @classmethod
    def register_options(cls, register):
        registries_help = (
            dedent(
                """\
                Configure Docker registries. The schema for a registry entry is as follows:

                    {
                        "registry-alias": {
                            "address": "registry-domain:port",
                            "default": bool,
                        },
                        ...
                    }

                """
            )
            + (
                "Only one registry may be declared as the default registry. If a registry value "
                "is not provided in a `docker_image` target, the address of the default registry "
                "will be used, if any.\n"
                "The `docker_image.registry` may be provided with either the registry address or "
                'the registry alias prefixed with `@`, or the empty string `""` if the image '
                "should not be associated with a custom registry.\n"
                "A configured registry is made default either by setting `default = true` or with "
                'an alias of `"default"`.'
            )
        )
        super().register_options(register)
        register("--registries", type=dict, fromfile=True, help=registries_help)

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self.options.registries)
