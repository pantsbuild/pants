# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from textwrap import dedent
from typing import cast

from pants.backend.docker.registries import DockerRegistries
from pants.option.custom_types import shell_str
from pants.option.errors import ParseError
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.strutil import bullet_list

doc_links = {
    "docker_env_vars": (
        "https://docs.docker.com/engine/reference/commandline/cli/#environment-variables"
    ),
}


def workspace_path(s: str) -> str:
    """Same type as 'str', but indicates string represents a directory path that is relative to
    either the build root, or a BUILD file if prefix with `./`.

    :API: public
    """
    if s.startswith("/"):
        raise ParseError(
            f"Invalid value: `{s}`. Expected a relative path, optionally in the form "
            "`./relative/path` to make it relative to the BUILD files rather than the build root."
        )
    return s


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
            "The value is formatted and may reference these variables (in addition to the normal "
            "placeheolders derived from the Dockerfile and build args etc):\n\n"
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
            "--default-context-root",
            type=workspace_path,
            default="",
            help=(
                "Provide a default Docker build context root path for `docker_image` targets that "
                "does not specify their own `context_root` field.\n\n"
                "The context root is relative to the build root by default, but may be prefixed "
                "with `./` to be relative to the directory of the BUILD file of the `docker_image`."
                "\n\nExamples:\n\n"
                "    --default-context-root=src/docker\n"
                "    --default-context-root=./relative_to_the_build_file\n"
            ),
        )

        register(
            "--build-args",
            type=list,
            member_type=shell_str,
            default=[],
            help=(
                "Global build arguments (for Docker `--build-arg` options) to use for all "
                "`docker build` invocations.\n\n"
                "Entries are either strings in the form `ARG_NAME=value` to set an explicit value; "
                "or just `ARG_NAME` to copy the value from Pants's own environment.\n\n"
                + dedent(
                    f"""\
                    Example:

                        [{cls.options_scope}]
                        build_args = ["VAR1=value", "VAR2"]

                    """
                )
                + "Use the `extra_build_args` field on a `docker_image` target for additional "
                "image specific build arguments."
            ),
        )

        register(
            "--build-target-stage",
            type=str,
            help=(
                "Global default value for `target_stage` on `docker_image` targets, overriding "
                "the field value on the targets, if there is a matching stage in the `Dockerfile`."
                "\n\n"
                "This is useful to provide from the command line, to specify the target stage to "
                "build for at execution time."
            ),
        )

        register(
            "--env-vars",
            type=list,
            member_type=shell_str,
            default=[],
            advanced=True,
            help=(
                "Environment variables to set for `docker` invocations.\n\n"
                "Entries are either strings in the form `ENV_VAR=value` to set an explicit value; "
                "or just `ENV_VAR` to copy the value from Pants's own environment."
            ),
        )

        register(
            "--run-args",
            type=list,
            member_type=shell_str,
            default=["--interactive", "--tty"] if sys.stdout.isatty() else [],
            help=(
                "Additional arguments to use for `docker run` invocations.\n\n"
                "Example:\n\n"
                f'    $ ./pants run --{cls.options_scope}-run-args="-p 127.0.0.1:80:8080/tcp '
                '--name demo" src/example:image -- [image entrypoint args]\n\n'
                "To provide the top-level options to the `docker` client, use "
                f"`[{cls.options_scope}].env_vars` to configure the [Environment variables]("
                f"{doc_links['docker_env_vars']}) as appropriate.\n\n"
                "The arguments for the image entrypoint may be passed on the command line after a "
                "double dash (`--`), or using the `--run-args` option.\n\n"
                "Defaults to `--interactive --tty` when stdout is connected to a terminal."
            ),
        )

    @property
    def build_args(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.options.build_args)))

    @property
    def build_target_stage(self) -> str | None:
        return cast("str | None", self.options.build_target_stage)

    @property
    def run_args(self) -> tuple[str, ...]:
        return tuple(self.options.run_args)

    @property
    def env_vars(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.options.env_vars)))

    @property
    def default_context_root(self) -> str:
        return cast(str, self.options.default_context_root)

    @property
    def default_repository(self) -> str:
        return cast(str, self.options.default_repository)

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self.options.registries)
