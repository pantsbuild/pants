# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.docker.registries import ALL_DEFAULT_REGISTRIES
from pants.core.goals.run import RestartableField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
)


class DockerBuildArgsField(StringSequenceField):
    alias = "extra_build_args"
    default = ()
    help = (
        "Build arguments (`--build-arg`) to use when building this image. "
        "Entries are either strings in the form `ARG_NAME=value` to set an explicit value; "
        "or just `ARG_NAME` to copy the value from Pants's own environment.\n\n"
        "Use `[docker].build_args` to set default build args for all images."
    )


class DockerImageSourceField(SingleSourceField):
    default = "Dockerfile"
    required = False
    help = "The Dockerfile to use when building the Docker image."


class DockerImageTagsField(StringSequenceField):
    alias = "image_tags"
    default = ("latest",)
    help = (
        "Any tags to apply to the Docker image name (the version is usually applied as a tag).\n\n"
        "Each tag may use placeholders in curly braces to be interpolated. The placeholders are "
        "derived from various sources, such as the Dockerfile FROM instructions tags and build "
        "args.\n\nSee {doc_url('tagging-docker-images')}."
    )


class DockerDependenciesField(Dependencies):
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


class DockerRepositoryField(StringField):
    alias = "repository"
    help = (
        'The repository name for the Docker image. e.g. "<repository>/<name>".\n\n'
        "It uses the `[docker].default_repository` by default."
        "This field value may contain format strings that will be interpolated at runtime. "
        "See the documentation for `[docker].default_repository` for details."
    )


class DockerSkipPushField(BoolField):
    alias = "skip_push"
    default = False
    help = "If set to true, do not push this image to registries when running `./pants publish`."


class DockerImage(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerBuildArgsField,
        DockerDependenciesField,
        DockerImageSourceField,
        DockerImageTagsField,
        DockerRegistriesField,
        DockerRepositoryField,
        DockerSkipPushField,
        RestartableField,
    )
    help = (
        "The `docker_image` target describes how to build and tag a Docker image.\n\n"
        "Any dependencies, as inferred or explicitly specified, will be included in the Docker "
        "build context, after being packaged if applicable."
    )
