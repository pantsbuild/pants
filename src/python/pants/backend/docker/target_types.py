# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.docker.subsystem import DEFAULT_REGISTRY
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, StringField, Target


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


class DockerRegistry(StringField):
    alias = "registry"
    default = DEFAULT_REGISTRY
    help = (
        "Address to Docker registry to use for the built image.\n\n"
        "This is either the domain name with optional port for your registry, or a registry alias "
        "prefixed with `@` for a registry configuration listed in the [docker].registries "
        "configuration section.\n"
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
                    registry = "@my-registry-alias" | "myregistrydomain:port" | ""
                )

            """
        )
        + (
            "The above example shows three valid `registry` options: using an alias to a configured "
            "registry, the address to a registry verbatim in the BUILD file, and last explicitly no "
            "registry even if there is a default registry configured."
        )
    )


class DockerImage(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerDependencies,
        DockerImageSources,
        DockerImageVersion,
        DockerRegistry,
    )
    help = "A Docker image."
