# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, StringField, Target


class DockerImageSources(Sources):
    expected_num_files = 1
    default = ("Dockerfile",)


class DockerImageVersion(StringField):
    alias = "version"
    default = "latest"
    help = "Image tag to apply to built images."


class DockerImage(Target):
    alias = "docker_image"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, DockerImageSources, DockerImageVersion)
    help = "A Docker image."
