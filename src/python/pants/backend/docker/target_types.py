# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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


class DockerContextRoot(StringField):
    alias = "context_root"
    default = None
    help = (
        "By default, the required files are assembled into a build context as follows:\n"
        "\n"
        " * The sources of `files` targets are assembled at their relative path from the "
        "repo root.\n"
        " * The sources of `resources` targets are assembled at their relative path from "
        "their source roots.\n"
        " * The artifacts of any packageable targets are built, as if by running "
        "`./pants package`, and placed in the context under a subdirectory named for the "
        "target's path from the repo root.\n"
        "\n"
        "[Advanced] By overriding with a custom value, the files will not be assembled, "
        "but rather left at their default locations, which may be outside of the Docker "
        "build context, and thus unusable for ADD/COPY commands in the `Dockerfile`."
    )


class DockerImage(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerContextRoot,
        DockerDependencies,
        DockerImageSources,
        DockerImageVersion,
    )
    help = "A Docker image."
