# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
import shlex
from abc import ABC, abstractmethod
from textwrap import dedent
from typing import ClassVar, Iterator

from typing_extensions import final

from pants.backend.docker.registries import ALL_DEFAULT_REGISTRIES
from pants.base.build_environment import get_buildroot
from pants.core.goals.run import RestartableField
from pants.engine.fs import GlobMatchErrorBehavior
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    DictStringToStringField,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.docutil import doc_url


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

    # When the default glob value is in effect, we don't want the normal glob match error behavior
    # to kick in for a missing Dockerfile, in case there are `instructions` provided, in which case
    # we generate the Dockerfile instead. If there are no `instructions`, or there are both
    # `instructions` and a Dockerfile hydrated from the `source` glob, we error out with a message
    # to the user.
    default_glob_match_error_behavior = GlobMatchErrorBehavior.ignore

    expected_num_files = range(0, 2)
    required = False
    help = (
        "The Dockerfile to use when building the Docker image.\n\n"
        "Use the `instructions` field instead if you prefer not having the Dockerfile in your "
        "project source tree."
    )


class DockerImageInstructionsField(StringSequenceField):
    alias = "instructions"
    required = False
    help = (
        "The `Dockerfile` content, typically one instruction per list item.\n\n"
        "Use the `source` field instead if you prefer having the Dockerfile in your project "
        "source tree.\n\n"
        + dedent(
            """\
            Example:

                # example/BUILD
                docker_image(
                  instructions=[
                    "FROM base/image:1.0",
                    "RUN echo example",
                  ],
                )
            """
        )
    )


class DockerImageTagsField(StringSequenceField):
    alias = "image_tags"
    default = ("latest",)
    help = (
        "Any tags to apply to the Docker image name (the version is usually applied as a tag).\n\n"
        "Each tag may use placeholders in curly braces to be interpolated. The placeholders are "
        "derived from various sources, such as the Dockerfile FROM instructions tags and build "
        f"args.\n\nSee {doc_url('tagging-docker-images')}."
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
                [docker.registries.my-registry-alias]
                address = "myregistrydomain:port"
                default = false  # optional

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


class DockerBuildOptionFieldMixin(ABC):
    """Inherit this mixin class to provide options to `docker build`."""

    docker_build_option: ClassVar[str]

    @abstractmethod
    def option_values(self) -> Iterator[str]:
        """Subclasses must implement this, to turn their `self.value` into none, one or more option
        values."""

    @final
    def options(self) -> Iterator[str]:
        for value in self.option_values():
            yield f"{self.docker_build_option}={shlex.quote(value)}"


class DockerBuildSecretsOptionField(
    AsyncFieldMixin, DockerBuildOptionFieldMixin, DictStringToStringField
):
    alias = "secrets"
    help = (
        "Secret files to expose to the build (only if BuildKit enabled).\n\n"
        "Secrets may use absolute paths, or paths relative to your project build root, or the "
        "BUILD file if prefixed with `./`. The id should be valid as used by the Docker build "
        "`--secret` option. See [Docker secrets](https://docs.docker.com/engine/swarm/secrets/) "
        "for more information.\n\n"
        + dedent(
            """\
            Example:

                docker_image(
                    secrets={
                        "mysecret": "/var/secrets/some-secret",
                        "repo-secret": "src/proj/secrets/some-secret",
                        "target-secret": "./secrets/some-secret",
                    }
                )
            """
        )
    )

    docker_build_option = "--secret"

    def option_values(self) -> Iterator[str]:
        # os.path.join() discards preceeding parts if encountering an abs path, e.g. if the secret
        # `path` is an absolute path, the `buildroot` and `spec_path` will not be considered.  Also,
        # an empty path part is ignored.
        for secret, path in (self.value or {}).items():
            full_path = os.path.join(
                get_buildroot(),
                self.address.spec_path if re.match(r"\.{1,2}/", path) else "",
                path,
            )
            yield f"id={secret},src={os.path.normpath(full_path)}"


class DockerImageTarget(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerBuildArgsField,
        DockerDependenciesField,
        DockerImageSourceField,
        DockerImageInstructionsField,
        DockerImageTagsField,
        DockerRegistriesField,
        DockerRepositoryField,
        DockerBuildSecretsOptionField,
        DockerSkipPushField,
        RestartableField,
    )
    help = (
        "The `docker_image` target describes how to build and tag a Docker image.\n\n"
        "Any dependencies, as inferred or explicitly specified, will be included in the Docker "
        "build context, after being packaged if applicable.\n\n"
        "By default, will use a Dockerfile from the same directory as the BUILD file this target "
        "is defined in. Point at another file with the `source` field, or use the `instructions` "
        "field to have the Dockerfile contents verbatim directly in the BUILD file."
    )
