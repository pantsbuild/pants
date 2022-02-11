# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from textwrap import dedent
from typing import Any

from pants.backend.docker.registries import DockerRegistries
from pants.engine.environment import Environment
from pants.option.option_types import (
    DictOption,
    ShellStrListOption,
    StrListOption,
    StrOption,
    WorkspacePathOption,
)
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.memo import memoized_method
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list

doc_links = {
    "docker_env_vars": (
        "https://docs.docker.com/engine/reference/commandline/cli/#environment-variables"
    ),
}
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


class DockerOptions(Subsystem):
    options_scope = "docker"
    help = "Options for interacting with Docker."

    _registries = DictOption[Any]("--registries", help=registries_help).from_file()
    default_repository = StrOption(
        "--default-repository",
        help=default_repository_help,
        default="{name}",
    )
    default_context_root = WorkspacePathOption(
        "--default-context-root",
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
    _build_args = ShellStrListOption(
        "--build-args",
        help=(
            "Global build arguments (for Docker `--build-arg` options) to use for all "
            "`docker build` invocations.\n\n"
            "Entries are either strings in the form `ARG_NAME=value` to set an explicit value; "
            "or just `ARG_NAME` to copy the value from Pants's own environment.\n\n"
            + dedent(
                f"""\
                    Example:

                        [{options_scope}]
                        build_args = ["VAR1=value", "VAR2"]

                    """
            )
            + "Use the `extra_build_args` field on a `docker_image` target for additional "
            "image specific build arguments."
        ),
    )
    build_target_stage = StrOption(
        "--build-target-stage",
        help=(
            "Global default value for `target_stage` on `docker_image` targets, overriding "
            "the field value on the targets, if there is a matching stage in the `Dockerfile`."
            "\n\n"
            "This is useful to provide from the command line, to specify the target stage to "
            "build for at execution time."
        ),
    )
    _env_vars = ShellStrListOption(
        "--env-vars",
        help=(
            "Environment variables to set for `docker` invocations.\n\n"
            "Entries are either strings in the form `ENV_VAR=value` to set an explicit value; "
            "or just `ENV_VAR` to copy the value from Pants's own environment."
        ),
    ).advanced()
    run_args = ShellStrListOption(
        "--run-args",
        default=["--interactive", "--tty"] if sys.stdout.isatty() else [],
        help=(
            "Additional arguments to use for `docker run` invocations.\n\n"
            "Example:\n\n"
            f'    $ {bin_name()} run --{options_scope}-run-args="-p 127.0.0.1:80:8080/tcp '
            '--name demo" src/example:image -- [image entrypoint args]\n\n'
            "To provide the top-level options to the `docker` client, use "
            f"`[{options_scope}].env_vars` to configure the [Environment variables]("
            f"{doc_links['docker_env_vars']}) as appropriate.\n\n"
            "The arguments for the image entrypoint may be passed on the command line after a "
            "double dash (`--`), or using the `--run-args` option.\n\n"
            "Defaults to `--interactive --tty` when stdout is connected to a terminal."
        ),
    )
    _executable_search_paths = (
        StrListOption(
            "--executable-search-paths",
            default=["<PATH>"],
            help=(
                "The PATH value that will be used to find the Docker client and any tools required."
                "\n\n"
                'The special string `"<PATH>"` will expand to the contents of the PATH env var.'
            ),
        )
        .advanced()
        .metavar("<binary-paths>")
    )

    @property
    def build_args(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._build_args)))

    @property
    def env_vars(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._env_vars)))

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self._registries)

    @memoized_method
    def executable_search_path(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._executable_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))
