# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from os import path
from typing import Optional

from pants.engine.addresses import Address
from pants.engine.fs import GlobMatchErrorBehavior, PathGlobs
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, StringField, Target


class Dockerfile(StringField):
    alias = "dockerfile"
    default = "Dockerfile"
    help = "Name of the Dockerfile to use when building the docker image."

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address)
        return path.join(address.spec_path, value_or_default)


class DockerContext(Sources):
    help = (
        "A list of files and globs that belong to this docker image.\n\nPaths are relative to the BUILD "
        "file's directory. You can ignore files/globs by prefixing them with `!`.\n\nExample: "
        "`sources=['example.py', 'test_*.py', '!test_ignore.py']`.\n\n"
        "The files will be included in the docker build context, so they can be included in the image "
        "using COPY instructions in the Dockerfile."
    )


class DockerDependencies(Dependencies):
    help = "List dependencies to other packages to build and sources to include in the docker build context."


class DockerImageVersion(StringField):
    alias = "version"
    default = "latest"
    help = "Image tag to apply to built images."


class DockerImage(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerDependencies,
        DockerImageVersion,
        Dockerfile,
        DockerContext,
    )
    help = "A Docker image."
