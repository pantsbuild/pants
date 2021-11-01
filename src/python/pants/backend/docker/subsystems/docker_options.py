# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import cast

from pants.backend.docker.registries import DockerRegistries
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.strutil import bullet_list


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
        default_repository_help = (
            "Configure the default repository name used in the Docker image tag.\n\n"
            "The value is formatted and may reference these variables:\n\n"
            + bullet_list(["name", "directory", "parent_directory"])
            + "\n\n"
            'Example: `--default-repository="{directory}/{name}"`.\n\n'
            "The `name` variable is the `docker_image`'s target name, `directory` and "
            "`parent_directory` are the name of the directory in which the BUILD file is for the "
            "target, and its parent directory respectively.\n\n"
            "Use the `repository` field to set this value directly on a `docker_image` "
            "target.\nAny registries or tags are added to the image name as required, and should "
            "not be part of the repository name."
        )
        super().register_options(register)
        register("--registries", type=dict, fromfile=True, help=registries_help)
        register(
            "--default-repository",
            type=str,
            help=default_repository_help,
            default="{name}",
        )

        register(
            "--build-args",
            type=list,
            member_type=str,
            default=[],
            help=(
                "Global build arguments (`--build-arg`) to use for all `docker build` invocations. "
                "Entries are either strings in the form `ARG_NAME=value` to set an explicit value; "
                "or just `ARG_NAME` to copy the value from Pants's own environment.\n\n"
                "May be provided multiple times on the command line.\n\n"
                "Use the `extra_build_args` field on a `docker_image` target for additional image "
                "specific build arguments."
            ),
        )

        register(
            "--env-vars",
            type=list,
            member_type=str,
            default=[],
            advanced=True,
            help=(
                "Environment variables to set for `docker` invocations. "
                "Entries are either strings in the form `ENV_VAR=value` to set an explicit value; "
                "or just `ENV_VAR` to copy the value from Pants's own environment."
            ),
        )

    @property
    def build_args(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.options.build_args)))

    @property
    def env_vars(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.options.env_vars)))

    @property
    def default_repository(self) -> str:
        return cast(str, self.options.default_repository)

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self.options.registries)
