# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.environment import LOCAL_ENVIRONMENT_MATCHER, LOCAL_WORKSPACE_ENVIRONMENT_MATCHER
from pants.engine.platform import Platform
from pants.engine.process import ProcessCacheScope
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.enums import match
from pants.util.strutil import help_text


class EnvironmentField(StringField):
    alias = "environment"
    default = LOCAL_ENVIRONMENT_MATCHER
    value: str
    help = help_text(
        f"""
        Specify which environment target to consume environment-sensitive options from.

        Once environments are defined in `[environments-preview].names`, you can specify the environment
        for this target by its name. Any fields that are defined in that environment will override
        the values from options set by `pants.toml`, command line values, or environment variables.

        You can specify multiple valid environments by using `parametrize`. If
        `{LOCAL_ENVIRONMENT_MATCHER}` is specified, Pants will fall back to the `local_environment`
        defined for the current platform, or no environment if no such environment exists.
        """
    )


class FallbackEnvironmentField(StringField):
    alias = "fallback_environment"
    default = None


class CompatiblePlatformsField(StringSequenceField):
    alias = "compatible_platforms"
    default = tuple(plat.value for plat in Platform)
    valid_choices = Platform
    value: tuple[str, ...]
    help = help_text(
        f"""
        Which platforms this environment can be used with.

        This is used for Pants to automatically determine which environment target to use for
        the user's machine when the environment is set to the special value
        `{LOCAL_ENVIRONMENT_MATCHER}`. Currently, there cannot be more than one environment target
        registered in `[environments-preview].names` for a particular platform. If there is no
        environment target for a certain platform, Pants will use the options system instead to
        determine environment variables and executable search paths.
        """
    )


class LocalCompatiblePlatformsField(CompatiblePlatformsField):
    pass


class LocalFallbackEnvironmentField(FallbackEnvironmentField):
    help = help_text(
        f"""
        The environment to fallback to when this local environment cannot be used because the
        field `{CompatiblePlatformsField.alias}` is not compatible with the local host.

        Must be an environment name from the option `[environments-preview].names`, the
        special string `{LOCAL_ENVIRONMENT_MATCHER}` to use the relevant local environment, or the
        Python value `None` to error when this specific local environment cannot be used.

        Tip: when targeting Linux, it can be particularly helpful to fallback to a
        `docker_environment` or `remote_environment` target. That allows you to prefer using the
        local host when possible, which often has less overhead (particularly compared to Docker).
        If the local host is not compatible, then Pants will use Docker or remote execution to
        still run in a similar environment.
        """
    )


class LocalEnvironmentTarget(Target):
    alias = "local_environment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        LocalCompatiblePlatformsField,
        LocalFallbackEnvironmentField,
    )
    help = help_text(
        f"""
        Configuration of a local execution environment for specific platforms.

        Environment configuration includes the platforms the environment is compatible with, and
        optionally a fallback environment, along with environment-aware options (such as
        environment variables and search paths) used by Pants to execute processes in this
        environment.

        To use this environment, map this target's address with a memorable name in
        `[environments-preview].names`. You can then consume this environment by specifying the name in
        the `environment` field defined on other targets.

        Only one `local_environment` may be defined in `[environments-preview].names` per platform, and
        when `{LOCAL_ENVIRONMENT_MATCHER}` is specified as the environment, the
        `local_environment` that matches the current platform (if defined) will be selected.

        See https://www.pantsbuild.org/stable/docs/using-pants/environments for more information.
        """
    )


class LocalWorkspaceCompatiblePlatformsField(CompatiblePlatformsField):
    pass


class LocalWorkspaceEnvironmentTarget(Target):
    alias = "experimental_workspace_environment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        LocalWorkspaceCompatiblePlatformsField,
    )
    help = help_text(
        f"""
        Configuration of a "workspace" execution environment for specific platforms.

        A "workspace" environment is a local environment which executes build processes within
        the repository and not in the usual execution sandbox. This is useful when interacting with
        third-party build orchestration tools which may not run correctly when run from within the Pants
        execution sandbox.

        Environment configuration includes the platforms the environment is compatible with along with
        environment-aware options (such as environment variables and search paths) used by Pants to execute
        processes in this environment.

        To use this environment, map this target's address with a memorable name in
        `[environments-preview].names`. You can then consume this environment by specifying the name in
        the `environment` field defined on other targets.

        Only one `experimental_workspace_environment` may be defined in `[environments-preview].names` per platform, and
        when `{LOCAL_WORKSPACE_ENVIRONMENT_MATCHER}` is specified as the environment, the
        `experimental_workspace_environment` that matches the current platform (if defined) will be selected.

        Caching and reproducibility:

        Pants' caching relies on all process being reproducible based solely on inputs in the repository.
        Processes executed in a workspace environment can easily accidentally read unexpected files,
        that aren't specified as a dependency.  Thus, Pants puts that burden on you, the Pants user, to ensure
        a process output only depends on its specified input files, and doesn't read anything else.

        If a process isn't reproducible, re-running a build from the same source code could fail unexpectedly,
        or give different output to an earlier build.

        NOTE: This target type is EXPERIMENTAL and may change its semantics in subsequent Pants versions
        without a deprecation cycle.
        """
    )


class DockerImageField(StringField):
    alias = "image"
    required = True
    value: str
    help = help_text(
        """
        The docker image ID to use when this environment is loaded.

        This value may be any image identifier that the local Docker installation can accept.
        This includes image names with or without tags (e.g. `centos6` or `centos6:latest`), or
        image names with an immutable digest (e.g. `centos@sha256:<some_sha256_value>`).

        The choice of image ID can affect the reproducibility of builds. Consider using an
        immutable digest if reproducibility is needed, but regularly ensure that the image
        is free of relevant bugs or security vulnerabilities.

        Note that in order to use an image as a `docker_environment` it must have a few tools:
        - `/bin/sh`
        - `/usr/bin/env`
        - `bash`
        - `tar`

        While most images will have these preinstalled, users of base images such as Distroless or scratch will need to bake these tools into the image themselves. All of these except `bash` are available via busybox.
        """
    )


class DockerPlatformField(StringField):
    alias = "platform"
    default = None
    valid_choices = Platform
    help = help_text(
        """
        If set, Docker will always use the specified platform when pulling and running the image.

        If unset, Pants will default to the CPU architecture of your local host machine. For
        example, if you are running on Apple Silicon, it will use `linux_arm64`, whereas running on
        Intel macOS will use `linux_x86_64`. This mirrors Docker's behavior when `--platform` is
        left off.
        """
    )

    @property
    def normalized_value(self) -> Platform:
        if self.value is not None:
            return Platform(self.value)
        return match(
            Platform.create_for_localhost(),
            {
                Platform.linux_x86_64: Platform.linux_x86_64,
                Platform.macos_x86_64: Platform.linux_x86_64,
                Platform.linux_arm64: Platform.linux_arm64,
                Platform.macos_arm64: Platform.linux_arm64,
            },
        )


class DockerFallbackEnvironmentField(FallbackEnvironmentField):
    help = help_text(
        f"""
        The environment to fallback to when this Docker environment cannot be used because either
        the global option `--docker-execution` is false, or the
        field `{DockerPlatformField.alias}` is not compatible with the local host's CPU
        architecture (this is only an issue when the local host is Linux; macOS is fine).

        Must be an environment name from the option `[environments-preview].names`, the
        special string `{LOCAL_ENVIRONMENT_MATCHER}` to use the relevant local environment, or the
        Python value `None` to error when this specific Docker environment cannot be used.
        """
    )


class DockerEnvironmentTarget(Target):
    alias = "docker_environment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        DockerImageField,
        DockerPlatformField,
        DockerFallbackEnvironmentField,
    )
    help = help_text(
        """
        Configuration of a Docker environment used for building your code.

        Environment configuration includes both Docker-specific information (including the image
        and platform choice), as well as environment-aware options (such as environment variables
        and search paths) used by Pants to execute processes in this Docker environment.

        To use this environment, map this target's address with a memorable name in
        `[environments-preview].names`. You can then consume this environment by specifying the name in
        the `environment` field defined on other targets.

        Before running Pants using this environment, if you are using Docker Desktop, make sure the option
        **Enable default Docker socket** is enabled, you can find it in **Docker Desktop Settings > Advanced**
        panel. That option tells Docker to create a socket at `/var/run/docker.sock` which Pants can use to
        communicate with Docker.

        See https://www.pantsbuild.org/stable/docs/using-pants/environments for more information.
        """
    )


class RemotePlatformField(StringField):
    alias = "platform"
    default = Platform.linux_x86_64.value
    valid_choices = Platform
    help = "The platform used by the remote execution environment."


class RemoteExtraPlatformPropertiesField(StringSequenceField):
    alias = "extra_platform_properties"
    default = ()
    value: tuple[str, ...]
    help = help_text(
        """
        Platform properties to set on remote execution requests.

        Format: `property=value`. Multiple values should be specified as multiple
        occurrences of this flag.

        Pants itself may add additional platform properties.
        """
    )


class RemoteFallbackEnvironmentField(FallbackEnvironmentField):
    help = help_text(
        f"""
        The environment to fallback to when remote execution is disabled via the global option
        `--remote-execution`.

        Must be an environment name from the option `[environments-preview].names`, the
        special string `{LOCAL_ENVIRONMENT_MATCHER}` to use the relevant local environment, or the
        Python value `None` to error when remote execution is disabled.

        Tip: if you are using a Docker image with your remote execution environment (usually
        enabled by setting the field `{RemoteExtraPlatformPropertiesField.alias}`), then it can be
        useful to fallback to an equivalent `docker_image` target so that you have a consistent
        execution environment.
        """
    )


class RemoteEnvironmentCacheBinaryDiscovery(BoolField):
    alias = "cache_binary_discovery"
    default = False
    help = help_text(
        f"""
        If true, will cache system binary discovery, e.g. finding Python interpreters.

        When safe to do, it is preferable to set this option to `True` for faster performance by
        avoiding wasted work. Otherwise, Pants will search for system binaries whenever the
        Pants daemon is restarted.

        However, it is only safe to set this to `True` if the remote execution environment has a
        stable environment, e.g. the server will not change versions of installed system binaries.
        Otherwise, you risk caching results that become stale when the server changes its
        environment, which may break your builds. With some remote execution servers, you can
        specify a Docker image to run with via the field
        `{RemoteExtraPlatformPropertiesField.alias}`; if you are able to specify what Docker image
        to use, and also use a pinned tag of the image, it is likely safe to set this field to true.
        """
    )


class RemoteEnvironmentTarget(Target):
    alias = "remote_environment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RemotePlatformField,
        RemoteExtraPlatformPropertiesField,
        RemoteFallbackEnvironmentField,
        RemoteEnvironmentCacheBinaryDiscovery,
    )
    help = help_text(
        """
        Configuration of a remote execution environment used for building your code.

        Environment configuration includes platform properties and a fallback environment, as well
        as environment-aware options (such as environment variables and search paths) used by Pants
        to execute processes in this remote environment.

        Note that you must also configure remote execution with the global options like
        `remote_execution` and `remote_execution_address`.

        To use this environment, map this target's address with a memorable name in
        `[environments-preview].names`. You can then consume this environment by specifying the name in
        the `environment` field defined on other targets.

        Often, it is only necessary to have a single `remote_environment` target for your
        repository, but it can be useful to have >1 so that you can set different
        `extra_platform_properties`. For example, with some servers, you could use this to
        configure a different Docker image per environment.

        See https://www.pantsbuild.org/stable/docs/using-pants/environments for more information.
        """
    )


@dataclass(frozen=True)
class EnvironmentTarget:
    name: str | None
    val: Target | None

    def executable_search_path_cache_scope(
        self, *, cache_failures: bool = False
    ) -> ProcessCacheScope:
        """Whether it's safe to cache executable search path discovery or not.

        If the environment may change on us, e.g. the user upgrades a binary, then it's not safe to
        cache the discovery to disk. Technically, in that case, we should recheck the binary every
        session (i.e. Pants run), but we instead settle for every Pantsd lifetime to have more
        acceptable performance.

        Meanwhile, when running with Docker, we already invalidate whenever the image changes
        thanks to https://github.com/pantsbuild/pants/pull/17101.

        Remote execution often is safe to cache, but depends on the remote execution server.
        So, we rely on the user telling us what is safe.
        """
        caching_allowed = self.val and (
            self.val.has_field(DockerImageField)
            or (
                self.val.has_field(RemoteEnvironmentCacheBinaryDiscovery)
                and self.val[RemoteEnvironmentCacheBinaryDiscovery].value
            )
        )
        if cache_failures:
            return (
                ProcessCacheScope.ALWAYS
                if caching_allowed
                else ProcessCacheScope.PER_RESTART_ALWAYS
            )
        return (
            ProcessCacheScope.SUCCESSFUL
            if caching_allowed
            else ProcessCacheScope.PER_RESTART_SUCCESSFUL
        )

    def sandbox_base_path(self) -> str:
        if self.val and self.val.has_field(LocalWorkspaceCompatiblePlatformsField):
            return "{chroot}"
        else:
            return ""

    @property
    def default_cache_scope(self) -> ProcessCacheScope:
        if self.val and self.val.has_field(LocalWorkspaceCompatiblePlatformsField):
            return ProcessCacheScope.PER_SESSION
        else:
            return ProcessCacheScope.SUCCESSFUL

    @property
    def use_working_directory_as_base_for_output_captures(self) -> bool:
        if self.val and self.val.has_field(LocalWorkspaceCompatiblePlatformsField):
            return False
        return True

    @property
    def can_access_local_system_paths(self) -> bool:
        tgt = self.val
        if not tgt:
            return True

        return tgt.has_field(LocalCompatiblePlatformsField) or tgt.has_field(
            LocalWorkspaceCompatiblePlatformsField
        )
