# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.docker.registries import ALL_DEFAULT_REGISTRIES
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)


class DockerImageSources(Sources):
    default = ("Dockerfile",)
    expected_num_files = 1
    help = "The Dockerfile to use when building the Docker image."


class DockerImageVersion(StringField):
    alias = "version"
    default = "latest"
    help = "Image tag to apply to built images."


class DockerDependencies(Dependencies):
    supports_transitive_excludes = True


class DockerRegistriesField(StringSequenceField):
    alias = "registries"
    default = (ALL_DEFAULT_REGISTRIES,)
    help = (
        "List of addresses or configured aliases to any Docker registries to use for the "
        "built image.\n\n"
        "The address is a domain name with optional port for your registry, and any registry "
        "aliases are prefixed with `@` for addresses in the [docker].registries configuration "
        "section.\n\n"
        "By default, all configured registries with `default = true` are used.\n\n"
        + dedent(
            """\
            Example:

                # pants.toml
                [docker]
                registries = "@registries.yaml"

                # registries.yaml
                my-registry-alias:
                    address = "myregistrydomain:port"
                    default = False  # optional

                # example/BUILD
                docker_image(
                    registries = [
                        "@my-registry-alias",
                        "myregistrydomain:port",
                    ],
                )

            """
        )
        + (
            "The above example shows two valid `registry` options: using an alias to a configured "
            "registry and the address to a registry verbatim in the BUILD file."
        )
    )


class DockerImage(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerDependencies,
        DockerImageSources,
        DockerImageVersion,
        DockerRegistriesField,
    )
    help = "A Docker image."
