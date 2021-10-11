# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.docker.registries import ALL_DEFAULT_REGISTRIES
from pants.core.goals.run import RestartableField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    MultipleSourcesField,
    StringField,
    StringSequenceField,
    Target,
)


class DockerImageSources(MultipleSourcesField):
    default = ("Dockerfile",)
    expected_num_files = 1
    help = "The Dockerfile to use when building the Docker image."


class DockerImageVersion(StringField):
    alias = "version"
    default = "latest"
    help = "Image tag to apply to built images."


class DockerImageName(StringField):
    alias = "image_name"
    help = (
        "The Docker image name, defaults is to use the target name.\n\n"
        "Note that the final image name(s) is made up of registries, repository, name and "
        "tags, which involves several fields from this target."
    )


class DockerImageNameTemplate(StringField):
    alias = "image_name_template"
    help = (
        "To override the default `[docker].default_image_name_template` configuration. See the "
        "documentation for that configuration option for how to use this value."
    )


class DockerImageTags(StringSequenceField):
    alias = "image_tags"
    help = (
        "Any tags to apply to the Docker image name, in addition to the default from the "
        "`version` field."
    )


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


class DockerRepository(StringField):
    alias = "repository"
    help = (
        "The repository part for the Docker image name.\n\n"
        "By default, it uses the directory name of the BUILD file for this target."
    )


class DockerSkipPushField(BoolField):
    alias = "skip_push"
    default = False
    help = "If set to true, do not push this image to registries when running `./pants publish`."


class DockerImage(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerDependencies,
        DockerImageName,
        DockerImageNameTemplate,
        DockerImageSources,
        DockerImageTags,
        DockerImageVersion,
        DockerRegistriesField,
        DockerRepository,
        DockerSkipPushField,
        RestartableField,
    )
    help = "A Docker image."
