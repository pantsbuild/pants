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
                "If no registries are provided in a `docker_image` target, then all default "
                "addresses will be used, if any.\n"
                "The `docker_image.registries` may be provided with a list of registry addresses "
                "and registry aliases prefixed with `@` to be used instead of the defaults.\n"
                "A configured registry is marked as default either by setting `default = true` "
                'or with an alias of `"default"`.'
            )
        )
        super().register_options(register)
        register("--registries", type=dict, fromfile=True, help=registries_help)

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self.options.registries)
