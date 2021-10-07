# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import cast

from pants.backend.docker.registries import DockerRegistries
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
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
        image_name_default = "{repository}/{name}"
        image_name_help = (
            "Configure the default template used to construct the final Docker image name.\n\n"
            "The template is a format string that may use these variables:\n\n"
            + bullet_list(["name", "repository", "sub_repository"])
            + "\n\n"
            "The `name` is the value of the `docker_image(image_name)` field, which defaults to "
            "the target name, and the `repository` is the `docker_image(repository)` field, which "
            "defaults to the name of the directory in which the BUILD file is for the target, and "
            "finally the `sub_repository` is like that of repository but including the parent "
            "directory as well.\n\n"
            "Use the `docker_image(image_name_template)` field to override this default template.\n"
            "Any registries or tags are added to the image name as required, and should not be "
            "part of the name template."
        )
        super().register_options(register)
        register("--registries", type=dict, fromfile=True, help=registries_help)
        register(
            "--default-image-name-template",
            type=str,
            help=image_name_help,
            default=image_name_default,
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
    def env_vars_to_pass_to_docker(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.options.env_vars)))

    @property
    def default_image_name_template(self) -> str:
        return cast(str, self.options.default_image_name_template)

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self.options.registries)


@dataclass(frozen=True)
class DockerEnvironmentVars:
    vars: FrozenDict[str, str]


@rule
async def get_docker_environment(
    docker: DockerOptions,
) -> DockerEnvironmentVars:
    return DockerEnvironmentVars(
        await Get(Environment, EnvironmentRequest(docker.env_vars_to_pass_to_docker))
    )


def rules():
    return collect_rules()
