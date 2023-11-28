# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, ClassVar, Iterator, Optional, cast

from typing_extensions import final

from pants.backend.docker.registries import ALL_DEFAULT_REGISTRIES
from pants.base.build_environment import get_buildroot
from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.environment import EnvironmentName
from pants.engine.fs import GlobMatchErrorBehavior
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    DictStringToStringField,
    Field,
    InvalidFieldException,
    OptionalSingleSourceField,
    StringField,
    StringSequenceField,
    Target,
    Targets,
)
from pants.engine.unions import union
from pants.util.docutil import bin_name, doc_url
from pants.util.frozendict import FrozenDict
from pants.util.strutil import help_text, softwrap

# Common help text to be applied to each field that supports value interpolation.
_interpolation_help = (
    "{kind} may use placeholders in curly braces to be interpolated. The placeholders are derived "
    "from various sources, such as the Dockerfile instructions and build args."
)


class DockerImageBuildArgsField(StringSequenceField):
    alias = "extra_build_args"
    default = ()
    help = help_text(
        """
        Build arguments (`--build-arg`) to use when building this image.
        Entries are either strings in the form `ARG_NAME=value` to set an explicit value;
        or just `ARG_NAME` to copy the value from Pants's own environment.

        Use `[docker].build_args` to set default build args for all images.
        """
    )


class DockerImageContextRootField(StringField):
    alias = "context_root"
    help = help_text(
        """
        Specify which directory to use as the Docker build context root. This affects the file
        paths to use for the `COPY` and `ADD` instructions. For example, whether
        `COPY files/f.txt` should look for the file relative to the build root:
        `<build root>/files/f.txt` vs relative to the BUILD file:
        `<build root>/path_to_build_file/files/f.txt`.

        Specify the `context_root` path as `files` for relative to build root, or as `./files`
        for relative to the BUILD file.

        If `context_root` is not specified, it defaults to `[docker].default_context_root`.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address=address)
        if isinstance(value_or_default, str) and value_or_default.startswith("/"):
            val = value_or_default.strip("/")
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The `{cls.alias}` field in target {address} must be a relative path, but was
                    {value_or_default!r}. Use {val!r} for a path relative to the build root, or
                    {'./' + val!r} for a path relative to the BUILD file
                    (i.e. {os.path.join(address.spec_path, val)!r}).
                    """
                )
            )
        return value_or_default


class DockerImageSourceField(OptionalSingleSourceField):
    none_is_valid_value = True
    default = "Dockerfile"

    # When the default glob value is in effect, we don't want the normal glob match error behavior
    # to kick in for a missing Dockerfile, in case there are `instructions` provided, in which case
    # we generate the Dockerfile instead. If there are no `instructions`, or there are both
    # `instructions` and a Dockerfile hydrated from the `source` glob, we error out with a message
    # to the user.
    default_glob_match_error_behavior = GlobMatchErrorBehavior.ignore

    help = help_text(
        """
        The Dockerfile to use when building the Docker image.

        Use the `instructions` field instead if you prefer not having the Dockerfile in your
        source tree.
        """
    )


class DockerImageInstructionsField(StringSequenceField):
    alias = "instructions"
    required = False
    help = help_text(
        """
        The `Dockerfile` content, typically one instruction per list item.

        Use the `source` field instead if you prefer having the Dockerfile in your source tree.

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


class DockerImageTagsField(StringSequenceField):
    alias = "image_tags"
    default = ("latest",)
    help = help_text(
        f"""

        Any tags to apply to the Docker image name (the version is usually applied as a tag).

        {_interpolation_help.format(kind="tag")}

        See {doc_url('tagging-docker-images')}.
        """
    )


class DockerImageTargetStageField(StringField):
    alias = "target_stage"
    help = help_text(
        """
        Specify target build stage, rather than building the entire `Dockerfile`.

        When using multi-stage build, you may name your stages, and can target them when building
        to only selectively build a certain stage. See also the `--docker-build-target-stage`
        option.

        Read more about [multi-stage Docker builds](https://docs.docker.com/develop/develop-images/multistage-build/#stop-at-a-specific-build-stage)
        """
    )


class DockerImageDependenciesField(Dependencies):
    supports_transitive_excludes = True


class DockerImageRegistriesField(StringSequenceField):
    alias = "registries"
    default = (ALL_DEFAULT_REGISTRIES,)
    help = help_text(
        """
        List of addresses or configured aliases to any Docker registries to use for the
        built image.

        The address is a domain name with optional port for your registry, and any registry
        aliases are prefixed with `@` for addresses in the `[docker].registries` configuration
        section.

        By default, all configured registries with `default = true` are used.

        Example:

            # pants.toml
            [docker.registries.my-registry-alias]
            address = "myregistrydomain:port"
            default = false # optional

            # example/BUILD
            docker_image(
                registries = [
                    "@my-registry-alias",
                    "myregistrydomain:port",
                ],
            )

        The above example shows two valid `registry` options: using an alias to a configured
        registry and the address to a registry verbatim in the BUILD file.
        """
    )


class DockerImageRepositoryField(StringField):
    alias = "repository"
    help = help_text(
        f"""
        The repository name for the Docker image. e.g. `"<repository>/<name>"`.

        It uses the `[docker].default_repository` by default.

        {_interpolation_help.format(kind="Repository")}

        Additional placeholders for the repository field are: `name`, `directory`,
        `parent_directory`, and `default_repository`.

        Registries may also configure the repository value for specific registries.

        See the documentation for `[docker].default_repository` for more information.
        """
    )


class DockerImageSkipPushField(BoolField):
    alias = "skip_push"
    default = False
    help = f"If true, do not push this image to registries when running `{bin_name()} publish`."


OptionValueFormatter = Callable[[str], str]


class DockerBuildOptionFieldMixin(ABC):
    """Inherit this mixin class to provide options to `docker build`."""

    docker_build_option: ClassVar[str]

    @abstractmethod
    def option_values(
        self, *, value_formatter: OptionValueFormatter, global_build_hosts_options: dict
    ) -> Iterator[str]:
        """Subclasses must implement this, to turn their `self.value` into none, one or more option
        values."""

    @final
    def options(
        self, value_formatter: OptionValueFormatter, global_build_hosts_options
    ) -> Iterator[str]:
        for value in self.option_values(
            value_formatter=value_formatter, global_build_hosts_options=global_build_hosts_options
        ):
            yield from (self.docker_build_option, value)


class DockerImageBuildImageLabelsOptionField(DockerBuildOptionFieldMixin, DictStringToStringField):
    alias = "image_labels"
    help = help_text(
        f"""
        Provide image metadata.

        {_interpolation_help.format(kind="Label value")}

        See [Docker labels](https://docs.docker.com/config/labels-custom-metadata/#manage-labels-on-objects)
        for more information.
        """
    )
    docker_build_option = "--label"

    def option_values(self, value_formatter: OptionValueFormatter, **kwargs) -> Iterator[str]:
        for label, value in (self.value or {}).items():
            yield f"{label}={value_formatter(value)}"


class DockerImageBuildImageExtraHostsField(DockerBuildOptionFieldMixin, DictStringToStringField):
    alias = "extra_build_hosts"
    help = help_text(
        """
        Extra hosts entries to be added to a container's `/etc/hosts` file.

        Use `[docker].build_hosts` to set default host entries for all images.
        """
    )
    docker_build_option = "--add-host"

    def option_values(
        self, value_formatter: OptionValueFormatter, global_build_hosts_options: dict = {}
    ) -> Iterator[str]:
        if self.value:
            merged_values = {**global_build_hosts_options, **self.value}
            for label, value in merged_values.items():
                yield f"{label}:{value_formatter(value)}"


class DockerBuildOptionFieldMultiValueDictMixin(DictStringToStringField):
    """Inherit this mixin class to provide options in the form of `--flag=key1=value1,key2=value2`
    to `docker build`."""

    docker_build_option: ClassVar[str]

    @final
    def options(self, value_formatter: OptionValueFormatter, **kwargs) -> Iterator[str]:
        if self.value:
            yield f"{self.docker_build_option}=" + ",".join(
                f"{key}={value_formatter(value)}" for key, value in self.value.items()
            )


class DockerBuildKitOptionField:
    """Mixin to indicate a BuildKit-specific option."""

    @abstractmethod
    def options(self, value_formatter: OptionValueFormatter) -> Iterator[str]:
        ...

    required_help = "This option requires BuildKit to be enabled via the Docker subsystem options."


class DockerImageBuildImageCacheToField(
    DockerBuildOptionFieldMultiValueDictMixin, DictStringToStringField, DockerBuildKitOptionField
):
    alias = "cache_to"
    help = help_text(
        f"""
        Export image build cache to an external cache destination.

        {DockerBuildKitOptionField.required_help}

        Example:

            docker_image(
                name="example-local-cache-backend",
                cache_to={{
                    "type": "local",
                    "dest": "/tmp/docker-cache/example"
                }},
                cache_from={{
                    "type": "local",
                    "src": "/tmp/docker-cache/example"
                }}
            )

        {_interpolation_help.format(kind="Values")}
        """
    )
    docker_build_option = "--cache-to"


class DockerImageBuildImageCacheFromField(
    DockerBuildOptionFieldMultiValueDictMixin, DictStringToStringField, DockerBuildKitOptionField
):
    alias = "cache_from"
    help = help_text(
        f"""
        Use an external cache source when building the image.

        {DockerBuildKitOptionField.required_help}

        Example:

            docker_image(
                name="example-local-cache-backend",
                cache_to={{
                    "type": "local",
                    "dest": "/tmp/docker-cache/example"
                }},
                cache_from={{
                    "type": "local",
                    "src": "/tmp/docker-cache/example"
                }}
            )

        {_interpolation_help.format(kind="Values")}
        """
    )
    docker_build_option = "--cache-from"


class DockerImageBuildImageOutputField(
    DockerBuildOptionFieldMultiValueDictMixin, DictStringToStringField, DockerBuildKitOptionField
):
    alias = "output"
    default = FrozenDict({"type": "docker"})
    help = help_text(
        f"""
        Sets the export action for the build result.

        {DockerBuildKitOptionField.required_help}

        When using `pants publish` to publish Docker images to a registry, the output type
        must be 'docker', as `publish` expects that the built images exist in the local
        image store.

        Currently, multi-platform images cannot be exported with the 'docker' export type,
        although experimental support is available with the [containerd image store](https://docs.docker.com/desktop/containerd/)

        {_interpolation_help.format(kind="Values")}
        """
    )
    docker_build_option = "--output"


class DockerImageBuildSecretsOptionField(
    AsyncFieldMixin, DockerBuildOptionFieldMixin, DictStringToStringField
):
    alias = "secrets"
    help = help_text(
        """
        Secret files to expose to the build (only if BuildKit enabled).

        Secrets may use absolute paths, or paths relative to your build root, or the BUILD file
        if prefixed with `./`. Paths to your home directory will be automatically expanded.
        The id should be valid as used by the Docker build `--secret` option.
        See [Docker secrets](https://docs.docker.com/engine/swarm/secrets/) for more
        information.

        Example:

            docker_image(
                secrets={
                    "mysecret": "/var/secrets/some-secret",
                    "repo-secret": "src/proj/secrets/some-secret",
                    "home-dir-secret": "~/.config/some-secret",
                    "target-secret": "./secrets/some-secret",
                }
            )
        """
    )

    docker_build_option = "--secret"

    def option_values(self, **kwargs) -> Iterator[str]:
        # os.path.join() discards preceding parts if encountering an abs path, e.g. if the secret
        # `path` is an absolute path, the `buildroot` and `spec_path` will not be considered.  Also,
        # an empty path part is ignored.
        for secret, path in (self.value or {}).items():
            full_path = os.path.join(
                get_buildroot(),
                self.address.spec_path if re.match(r"\.{1,2}/", path) else "",
                os.path.expanduser(path),
            )

            yield f"id={secret},src={os.path.normpath(full_path)}"


class DockerImageBuildSSHOptionField(DockerBuildOptionFieldMixin, StringSequenceField):
    alias = "ssh"
    default = ()
    help = help_text(
        """
        SSH agent socket or keys to expose to the build (only if BuildKit enabled)
        (format: `default|<id>[=<socket>|<key>[,<key>]]`)

        The exposed agent and/or keys can then be used in your `Dockerfile` by mounting them in
        your `RUN` instructions:

            RUN --mount=type=ssh ...

        See [Docker documentation](https://docs.docker.com/develop/develop-images/build_enhancements/#using-ssh-to-access-private-data-in-builds)
        for more information.
        """
    )

    docker_build_option = "--ssh"

    def option_values(self, **kwargs) -> Iterator[str]:
        yield from cast("tuple[str]", self.value)


class DockerBuildOptionFieldValueMixin(Field):
    """Inherit this mixin class to provide unary options (i.e. option in the form of `--flag=value`)
    to `docker build`."""

    docker_build_option: ClassVar[str]

    @final
    def options(self, *args, **kwargs) -> Iterator[str]:
        if self.value is not None:
            yield f"{self.docker_build_option}={self.value}"


class DockerBuildOptionFieldMultiValueMixin(StringSequenceField):
    """Inherit this mixin class to provide options in the form of `--flag=value1,value2` to `docker
    build`."""

    docker_build_option: ClassVar[str]

    @final
    def options(self, *args, **kwargs) -> Iterator[str]:
        if self.value:
            yield f"{self.docker_build_option}={','.join(list(self.value))}"


class DockerImageBuildPullOptionField(DockerBuildOptionFieldValueMixin, BoolField):
    alias = "pull"
    default = False
    help = help_text(
        """
        If true, then docker will always attempt to pull a newer version of the image.

        NOTE: This option cannot be used on images that build off of "transitive" base images
        referenced by address (i.e. `FROM path/to/your/base/Dockerfile`).
        """
    )
    docker_build_option = "--pull"


class DockerBuildOptionFlagFieldMixin(BoolField, ABC):
    """Inherit this mixin class to provide optional flags (i.e. add `--flag` only when the value is
    `True`) to `docker build`."""

    docker_build_option: ClassVar[str]

    @final
    def options(self, *args, **kwargs) -> Iterator[str]:
        if self.value:
            yield f"{self.docker_build_option}"


class DockerImageBuildSquashOptionField(DockerBuildOptionFlagFieldMixin):
    alias = "squash"
    default = False
    help = help_text(
        """
        If true, then docker will squash newly built layers into a single new layer.

        Note that this option is only supported on a Docker daemon with experimental features enabled.
        """
    )
    docker_build_option = "--squash"


class DockerImageBuildNetworkOptionField(DockerBuildOptionFieldValueMixin, StringField):
    alias = "build_network"
    default = None
    help = help_text(
        """
        Sets the networking mode for the run commands during build.
        Supported standard values are: bridge, host, none, and container:<name|id>.
        Any other value is taken as a custom network's name to which the container should connect to.
        """
    )
    docker_build_option = "--network"


class DockerImageBuildPlatformOptionField(
    DockerBuildOptionFieldMultiValueMixin, StringSequenceField
):
    alias = "build_platform"
    default = None
    help = help_text(
        """
        Set the target platform(s) for the build.
        """
    )
    docker_build_option = "--platform"


class DockerImageTarget(Target):
    alias = "docker_image"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerImageBuildArgsField,
        DockerImageDependenciesField,
        DockerImageSourceField,
        DockerImageInstructionsField,
        DockerImageContextRootField,
        DockerImageTagsField,
        DockerImageRegistriesField,
        DockerImageRepositoryField,
        DockerImageBuildImageLabelsOptionField,
        DockerImageBuildImageExtraHostsField,
        DockerImageBuildSecretsOptionField,
        DockerImageBuildSSHOptionField,
        DockerImageSkipPushField,
        DockerImageTargetStageField,
        DockerImageBuildPullOptionField,
        DockerImageBuildSquashOptionField,
        DockerImageBuildNetworkOptionField,
        DockerImageBuildPlatformOptionField,
        DockerImageBuildImageCacheToField,
        DockerImageBuildImageCacheFromField,
        DockerImageBuildImageOutputField,
        OutputPathField,
        RestartableField,
    )
    help = help_text(
        """
        The `docker_image` target describes how to build and tag a Docker image.

        Any dependencies, as inferred or explicitly specified, will be included in the Docker
        build context, after being packaged if applicable.

        By default, it will use a Dockerfile from the same directory as the BUILD file this target
        is defined in. Point at another file with the `source` field, or use the `instructions`
        field to have the Dockerfile contents verbatim directly in the BUILD file.

        Dependencies on upstream/base images defined by another `docker_image` are inferred if
        referenced by a build argument with a default value of the target address.

        Example:

            # src/docker/downstream/Dockerfile
            ARG BASE=src/docker/upstream:image
            FROM $BASE
            ...

        """
    )


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class DockerImageTagsRequest:
    """A request to provide additional image tags."""

    target: Target

    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        """Whether to provide additional tags for this target or not."""
        return True


class DockerImageTags(Collection[str]):
    """Additional image tags to apply to built Docker images."""


class AllDockerImageTargets(Targets):
    pass


@rule
def all_docker_targets(all_targets: AllTargets) -> AllDockerImageTargets:
    return AllDockerImageTargets(
        [tgt for tgt in all_targets if tgt.has_field(DockerImageSourceField)]
    )


def rules():
    return collect_rules()
