# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys
from typing import Any

from pants.backend.docker.registries import DockerRegistries
from pants.core.util_rules.search_paths import ExecutableSearchPathsOptionMixin
from pants.option.option_types import (
    BoolOption,
    DictOption,
    ShellStrListOption,
    StrListOption,
    StrOption,
    WorkspacePathOption,
)
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.memo import memoized_method
from pants.util.strutil import bullet_list, softwrap

doc_links = {
    "docker_env_vars": (
        "https://docs.docker.com/engine/reference/commandline/cli/#environment-variables"
    ),
}


class DockerOptions(Subsystem):
    options_scope = "docker"
    help = "Options for interacting with Docker."

    class EnvironmentAware(ExecutableSearchPathsOptionMixin, Subsystem.EnvironmentAware):
        _env_vars = ShellStrListOption(
            help=softwrap(
                """
                Environment variables to set for `docker` invocations.

                Entries are either strings in the form `ENV_VAR=value` to set an explicit value;
                or just `ENV_VAR` to copy the value from Pants's own environment.
                """
            ),
            advanced=True,
        )
        executable_search_paths_help = softwrap(
            """
            The PATH value that will be used to find the Docker client and any tools required.
            """
        )

        @property
        def env_vars(self) -> tuple[str, ...]:
            return tuple(sorted(set(self._env_vars)))

    _registries = DictOption[Any](
        help=softwrap(
            """
            Configure Docker registries. The schema for a registry entry is as follows:

                {
                    "registry-alias": {
                        "address": "registry-domain:port",
                        "default": bool,
                        "extra_image_tags": [],
                        "skip_push": bool,
                        "repository": str,
                        "use_local_alias": bool,
                    },
                    ...
                }

            If no registries are provided in a `docker_image` target, then all default
            addresses will be used, if any.

            The `docker_image.registries` may be provided with a list of registry addresses
            and registry aliases prefixed with `@` to be used instead of the defaults.

            A configured registry is marked as default either by setting `default = true`
            or with an alias of `"default"`.

            A `docker_image` may be pushed to a subset of registries using the per registry
            `skip_push` option rather then the all or nothing toggle of the field option `skip_push`
            on the `docker_image` target.

            Any image tags that should only be added for specific registries may be provided as the
            `extra_image_tags` option. The tags may use value formatting the same as for the
            `image_tags` field of the `docker_image` target.

            When a registry provides a `repository` value, it will be used instead of the
            `docker_image.repository` or the default repository. Using the placeholders
            `{target_repository}` or `{default_repository}` those overridden values may be
            incorporated into the registry specific repository value.

            If `use_local_alias` is true, a built image is additionally tagged locally using the
            registry alias as the value for repository (i.e. the additional image tag is not pushed)
            and will be used for any `pants run` requests.
            """
        ),
        fromfile=True,
    )
    default_repository = StrOption(
        help=softwrap(
            f"""
            Configure the default repository name used in the Docker image tag.

            The value is formatted and may reference these variables (in addition to the normal
            placeheolders derived from the Dockerfile and build args etc):

            {bullet_list(["name", "directory", "parent_directory", "target_repository"])}

            Example: `--default-repository="{{directory}}/{{name}}"`.

            The `name` variable is the `docker_image`'s target name, `directory` and
            `parent_directory` are the name of the directory in which the BUILD file is for the
            target, and its parent directory respectively.

            Use the `repository` field to set this value directly on a `docker_image` target.

            Registries may override the repository value for a specific registry.

            Any registries or tags are added to the image name as required, and should
            not be part of the repository name.
            """
        ),
        default="{name}",
    )
    default_context_root = WorkspacePathOption(
        default="",
        help=softwrap(
            """
            Provide a default Docker build context root path for `docker_image` targets that
            does not specify their own `context_root` field.

            The context root is relative to the build root by default, but may be prefixed
            with `./` to be relative to the directory of the BUILD file of the `docker_image`.

            Examples:

                --default-context-root=src/docker
                --default-context-root=./relative_to_the_build_file
            """
        ),
    )
    use_buildx = BoolOption(
        default=False,
        help=softwrap(
            f"""
            Use [buildx](https://github.com/docker/buildx#buildx) (and BuildKit) for builds.
            """
        ),
    )
    _build_args = ShellStrListOption(
        help=softwrap(
            f"""
            Global build arguments (for Docker `--build-arg` options) to use for all
            `docker build` invocations.

            Entries are either strings in the form `ARG_NAME=value` to set an explicit value;
            or just `ARG_NAME` to copy the value from Pants's own environment.

            Example:

                [{options_scope}]
                build_args = ["VAR1=value", "VAR2"]


            Use the `extra_build_args` field on a `docker_image` target for additional
            image specific build arguments.
            """
        ),
    )
    build_target_stage = StrOption(
        default=None,
        help=softwrap(
            """
            Global default value for `target_stage` on `docker_image` targets, overriding
            the field value on the targets, if there is a matching stage in the `Dockerfile`.

            This is useful to provide from the command line, to specify the target stage to
            build for at execution time.
            """
        ),
    )
    build_hosts = DictOption[str](
        default={},
        help=softwrap(
            f"""
            Hosts entries to be added to the `/etc/hosts` file in all built images.

            Example:

                [{options_scope}]
                build_hosts = {{"docker": "10.180.0.1", "docker2": "10.180.0.2"}}

            Use the `extra_build_hosts` field on a `docker_image` target for additional
            image specific host entries.
            """
        ),
    )
    build_no_cache = BoolOption(
        default=False,
        help="Do not use the Docker cache when building images.",
    )
    build_verbose = BoolOption(
        default=False,
        help="Whether to log the Docker output to the console. If false, only the image ID is logged.",
    )
    run_args = ShellStrListOption(
        default=["--interactive", "--tty"] if sys.stdout.isatty() else [],
        help=softwrap(
            f"""
            Additional arguments to use for `docker run` invocations.

            Example:

                $ {bin_name()} run --{options_scope}-run-args="-p 127.0.0.1:80:8080/tcp\
                    --name demo" src/example:image -- [image entrypoint args]

            To provide the top-level options to the `docker` client, use
            `[{options_scope}].env_vars` to configure the
            [Environment variables]({doc_links['docker_env_vars']}) as appropriate.

            The arguments for the image entrypoint may be passed on the command line after a
            double dash (`--`), or using the `--run-args` option.

            Defaults to `--interactive --tty` when stdout is connected to a terminal.
            """
        ),
    )
    _tools = StrListOption(
        default=[],
        help=softwrap(
            """
            List any additional executable tools required for Docker to work. The paths to
            these tools will be included in the PATH used in the execution sandbox, so that
            they may be used by the Docker client.
            """
        ),
        advanced=True,
    )

    tailor = BoolOption(
        default=True,
        help="If true, add `docker_image` targets with the `tailor` goal.",
        advanced=True,
    )

    @property
    def build_args(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._build_args)))

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._tools)))

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self._registries)
