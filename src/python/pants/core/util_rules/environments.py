# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import shlex
from dataclasses import dataclass
from itertools import groupby
from typing import Any, Callable, ClassVar, Iterable, Optional, Sequence, Tuple, Type, Union, cast

from pants.build_graph.address import Address, AddressInput
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.environment import LOCAL_ENVIRONMENT_MATCHER, LOCAL_WORKSPACE_ENVIRONMENT_MATCHER
from pants.engine.environment import ChosenLocalEnvironmentName as ChosenLocalEnvironmentName
from pants.engine.environment import (
    ChosenLocalWorkspaceEnvironmentName as ChosenLocalWorkspaceEnvironmentName,
)
from pants.engine.environment import EnvironmentName as EnvironmentName
from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.internals.graph import WrappedTargetForBootstrap
from pants.engine.internals.native_engine import ProcessExecutionEnvironment
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.platform import Platform
from pants.engine.process import ProcessCacheScope
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Field,
    FieldDefaultFactoryRequest,
    FieldDefaultFactoryResult,
    FieldSet,
    StringField,
    StringSequenceField,
    Target,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.option import custom_types
from pants.option.global_options import GlobalOptions
from pants.option.option_types import DictOption, OptionsInfo, collect_options_info
from pants.option.subsystem import Subsystem
from pants.util.enums import match
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized
from pants.util.strutil import bullet_list, help_text, softwrap

logger = logging.getLogger(__name__)


class EnvironmentsSubsystem(Subsystem):
    options_scope = "environments-preview"
    help = help_text(
        """
        A highly experimental subsystem to allow setting environment variables and executable
        search paths for different environments, e.g. macOS vs. Linux.
        """
    )

    names = DictOption[str](
        help=softwrap(
            """
            A mapping of logical names to addresses to environment targets. For example:

                [environments-preview.names]
                linux_local = "//:linux_env"
                macos_local = "//:macos_env"
                centos6 = "//:centos6_docker_env"
                linux_ci = "build-support:linux_ci_env"
                macos_ci = "build-support:macos_ci_env"

            To use an environment for a given target, specify the name in the `environment` field
            on that target. Pants will consume the environment target at the address mapped from
            that name.

            Pants will ignore any environment targets that are not given a name via this option.
            """
        )
    )

    def remote_execution_used_globally(self, global_options: GlobalOptions) -> bool:
        """If the environments mechanism is not used, `--remote-execution` toggles remote execution
        globally."""
        return not self.names and global_options.remote_execution


# -------------------------------------------------------------------------------------------
# Environment targets
# -------------------------------------------------------------------------------------------


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
        """
        # TODO(#17096) Add a link to the environments docs once they land.
    )


class LocalWorkspaceCompatiblePlatformsField(CompatiblePlatformsField):
    pass


class LocalWorkspaceEnvironmentTarget(Target):
    alias = "workspace_environment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        LocalWorkspaceCompatiblePlatformsField,
    )
    help = help_text(
        """
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

        Only one `workspace_environment` may be defined in `[environments-preview].names` per platform, and
        when `{LOCAL_WORKSPACE_ENVIRONMENT_MATCHER}` is specified as the environment, the
        `workspace_environment` that matches the current platform (if defined) will be selected.

        Caching and reproducibility:

        Pants' caching relies on all process being reproducible based solely on inputs in the repository.
        Processes executed in a workspace environment can easily accidentally read unexpected files,
        that aren't specified as a dependency.  Thus, Pants puts that burden on you, the Pants user, to ensure
        a process output only depends on its specified input files, and doesn't read anything else.

        If a process isn't reproducible, re-running a build from the same source code could fail unexpectedly,
        or give different output to an earlier build.
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


class DockerPlatformFieldDefaultFactoryRequest(FieldDefaultFactoryRequest):
    field_type = DockerPlatformField


@rule
def docker_platform_field_default_factory(
    _: DockerPlatformFieldDefaultFactoryRequest,
) -> FieldDefaultFactoryResult:
    return FieldDefaultFactoryResult(lambda f: f.normalized_value)


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
        """
        # TODO(#17096) Add a link to the environments docs once they land.
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
        """
        # TODO(#17096) Add a link to the environments docs once they land.
    )


# -------------------------------------------------------------------------------------------
# Rules
# -------------------------------------------------------------------------------------------


async def _warn_on_non_local_environments(specified_targets: Iterable[Target], source: str) -> None:
    """Raise a warning when the user runs a local-only operation against a target that expects a
    non-local environment.

    The `source` will be used to explain which goal is causing the issue.
    """

    env_names = [
        (target[EnvironmentField].value, target)
        for target in specified_targets
        if target.has_field(EnvironmentField)
    ]
    sorted_env_names = sorted(env_names, key=lambda en: (en[0], en[1].address.spec))

    env_names_and_targets = [
        (env_name, tuple(target for _, target in group))
        for env_name, group in groupby(sorted_env_names, lambda x: x[0])
    ]

    env_tgts = await MultiGet(
        Get(
            EnvironmentTarget,
            EnvironmentNameRequest(
                name,
                description_of_origin=(
                    "the `environment` field of targets including "
                    ", ".join(tgt.address.spec for tgt in tgts[:3])
                ),
            ),
        )
        for name, tgts in env_names_and_targets
    )

    error_cases = [
        (env_name, tgts, env_tgt.val)
        for ((env_name, tgts), env_tgt) in zip(env_names_and_targets, env_tgts)
        if env_tgt.val is not None and not isinstance(env_tgt.val, LocalEnvironmentTarget)
    ]

    for env_name, tgts, env_tgt in error_cases:
        # "Blah was called with target `//foo` which specifies…"
        # "Blah was called with targets `//foo`, `//bar` which specify…"
        # "Blah was called with targets including `//foo`, `//bar`, `//baz` (and others) which specify…"
        plural = len(tgts) > 1
        is_long = len(tgts) > 3
        tgt_specs = [tgt.address.spec for tgt in tgts[:3]]

        tgts_str = (
            ("s " if plural else " ")
            + ("including " if is_long else "")
            + ", ".join(f"`{i}`" for i in tgt_specs)
            + (" (and others)" if is_long else "")
        )
        end_specif = "y" if plural else "ies"

        logger.warning(
            f"{source.capitalize()} was called with target{tgts_str}, which specif{end_specif} "
            f"the environment `{env_name}`, which is a `{env_tgt.alias}`. {source.capitalize()} "
            "only runs in the local environment. You may experience unexpected behavior."
        )


def determine_bootstrap_environment(session: SchedulerSession) -> EnvironmentName:
    local_env = cast(
        ChosenLocalEnvironmentName,
        session.product_request(ChosenLocalEnvironmentName, [Params()])[0],
    )
    return local_env.val


class AmbiguousEnvironmentError(Exception):
    pass


class UnrecognizedEnvironmentError(Exception):
    pass


class NoFallbackEnvironmentError(Exception):
    pass


class AllEnvironmentTargets(FrozenDict[str, Target]):
    """A mapping of environment names to their corresponding environment target."""


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


def _compute_env_field(field_set: FieldSet) -> EnvironmentField:
    for attr in dir(field_set):
        # Skip what look like dunder methods, which are unlikely to be an
        # EnvironmentField value on FieldSet class declarations.
        if attr.startswith("__"):
            continue
        val = getattr(field_set, attr)
        if isinstance(val, EnvironmentField):
            return val
    return EnvironmentField(None, address=field_set.address)


@dataclass(frozen=True)
class EnvironmentNameRequest(EngineAwareParameter):
    f"""Normalize the value into a name from `[environments-preview].names`, such as by
    applying {LOCAL_ENVIRONMENT_MATCHER}."""

    raw_value: str
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

    @classmethod
    def from_target(cls, target: Target) -> EnvironmentNameRequest:
        f"""Return a `EnvironmentNameRequest` with the environment this target should use when built.

        If the Target includes `EnvironmentField` in its class definition, then this method will
        use the value of that field. Otherwise, it will fall back to `{LOCAL_ENVIRONMENT_MATCHER}`.
        """
        env_field = target.get(EnvironmentField)
        return cls._from_field(env_field, target.address)

    @classmethod
    def from_field_set(cls, field_set: FieldSet) -> EnvironmentNameRequest:
        f"""Return a `EnvironmentNameRequest` with the environment this target should use when built.

        If the FieldSet includes `EnvironmentField` in its class definition, then this method will
        use the value of that field. Otherwise, it will fall back to `{LOCAL_ENVIRONMENT_MATCHER}`.

        Rules can then use `Get(EnvironmentName, EnvironmentNameRequest,
        field_set.environment_name_request())` to normalize the environment value, and
        then pass `{{resulting_environment_name: EnvironmentName}}` into a `Get` to change which
        environment is used for the subgraph.
        """
        env_field = _compute_env_field(field_set)
        return cls._from_field(env_field, field_set.address)

    @classmethod
    def _from_field(cls, env_field: EnvironmentField, address: Address) -> EnvironmentNameRequest:
        return EnvironmentNameRequest(
            env_field.value,
            # Note that if the field was not registered, we will have fallen back to the default
            # LOCAL_ENVIRONMENT_MATCHER, which we expect to be infallible when normalized. That
            # implies that the error message using description_of_origin should not trigger, so
            # it's okay that the field is not actually registered on the target.
            description_of_origin=(f"the `{env_field.alias}` field from the target {address}"),
        )

    def debug_hint(self) -> str:
        return self.raw_value


@dataclass(frozen=True)
class SingleEnvironmentNameRequest(EngineAwareParameter):
    """Asserts that all of the given environment strings resolve to the same EnvironmentName."""

    raw_values: tuple[str, ...]
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

    @classmethod
    def from_field_sets(
        cls, field_sets: Sequence[FieldSet], description_of_origin: str
    ) -> SingleEnvironmentNameRequest:
        """See `EnvironmentNameRequest.from_field_set`."""

        return SingleEnvironmentNameRequest(
            tuple(sorted({_compute_env_field(field_set).value for field_set in field_sets})),
            description_of_origin=description_of_origin,
        )

    def debug_hint(self) -> str:
        return ", ".join(self.raw_values)


@rule
async def determine_all_environments(
    environments_subsystem: EnvironmentsSubsystem,
) -> AllEnvironmentTargets:
    resolved_tgts = await MultiGet(
        Get(EnvironmentTarget, EnvironmentName(name)) for name in environments_subsystem.names
    )
    return AllEnvironmentTargets(
        (name, resolved_tgt.val)
        for name, resolved_tgt in zip(environments_subsystem.names.keys(), resolved_tgts)
        if resolved_tgt.val is not None
    )


@rule
async def determine_local_environment(
    all_environment_targets: AllEnvironmentTargets,
) -> ChosenLocalEnvironmentName:
    platform = Platform.create_for_localhost()
    compatible_name_and_targets = [
        (name, tgt)
        for name, tgt in all_environment_targets.items()
        if tgt.has_field(LocalCompatiblePlatformsField)
        and platform.value in tgt[CompatiblePlatformsField].value
    ]
    if not compatible_name_and_targets:
        # That is, use the values from the options system instead, rather than from fields.
        return ChosenLocalEnvironmentName(EnvironmentName(None))

    if len(compatible_name_and_targets) == 1:
        result_name, _tgt = compatible_name_and_targets[0]
        return ChosenLocalEnvironmentName(EnvironmentName(result_name))

    raise AmbiguousEnvironmentError(
        softwrap(
            f"""
            Multiple `local_environment` targets from `[environments-preview].names`
            are compatible with the current platform `{platform.value}`, so it is ambiguous
            which to use:
            {sorted(tgt.address.spec for _name, tgt in compatible_name_and_targets)}

            To fix, either adjust the `{CompatiblePlatformsField.alias}` field from those
            targets so that only one includes the value `{platform.value}`, or change
            `[environments-preview].names` so that it does not define some of those targets.

            It is often useful to still keep the same `local_environment` target definitions in
            BUILD files; instead, do not give a name to each of them in
            `[environments-preview].names` to avoid ambiguity. Then, you can override which target
            a particular name points to by overriding `[environments-preview].names`. For example,
            you could set this in `pants.toml`:

                [environments-preview.names]
                linux = "//:linux_env"
                macos = "//:macos_local_env"

            Then, for CI, override what the name `macos` points to by setting this in
            `pants.ci.toml`:

                [environments-preview.names.add]
                macos = "//:macos_ci_env"

            Locally, you can override `[environments-preview].names` like this by using a
            `.pants.rc` file, for example.
            """
        )
    )


@rule
async def determine_local_workspace_environment(
    all_environment_targets: AllEnvironmentTargets,
) -> ChosenLocalWorkspaceEnvironmentName:
    platform = Platform.create_for_localhost()
    compatible_name_and_targets = [
        (name, tgt)
        for name, tgt in all_environment_targets.items()
        if tgt.has_field(LocalWorkspaceCompatiblePlatformsField)
        and platform.value in tgt[CompatiblePlatformsField].value
    ]

    if not compatible_name_and_targets:
        # Raise an exception since, unlike with `local_environment`, a `workspace_environment`
        # cannot be configured via global options.
        raise AmbiguousEnvironmentError(
            softwrap(
                f"""
                A target requested a compatible workspace environment via the
                `{LOCAL_WORKSPACE_ENVIRONMENT_MATCHER}` special environment name. No `workspace_environment`
                target exists, however, to satisfy that request.

                Unlike local environmnts, with workspace environments, at least one `workspace_environment`
                target must exist and be named in the `[environments-preview.names]` option.
                """
            )
        )

    if len(compatible_name_and_targets) == 1:
        result_name, _tgt = compatible_name_and_targets[0]
        return ChosenLocalWorkspaceEnvironmentName(EnvironmentName(result_name))

    raise AmbiguousEnvironmentError(
        softwrap(
            f"""
            Multiple `workspace_environment` targets from `[environments-preview].names`
            are compatible with the current platform `{platform.value}`, so it is ambiguous
            which to use:
            {sorted(tgt.address.spec for _name, tgt in compatible_name_and_targets)}

            To fix, either adjust the `{CompatiblePlatformsField.alias}` field from those
            targets so that only one includes the value `{platform.value}`, or change
            `[environments-preview].names` so that it does not define some of those targets.

            It is often useful to still keep the same `workspace_environment` target definitions in
            BUILD files; instead, do not give a name to each of them in
            `[environments-preview].names` to avoid ambiguity. Then, you can override which target
            a particular name points to by overriding `[environments-preview].names`. For example,
            you could set this in `pants.toml`:

                [environments-preview.names]
                linux = "//:linux_env"
                macos = "//:macos_local_env"

            Then, for CI, override what the name `macos` points to by setting this in
            `pants.ci.toml`:

                [environments-preview.names.add]
                macos = "//:macos_ci_env"

            Locally, you can override `[environments-preview].names` like this by using a
            `.pants.rc` file, for example.
            """
        )
    )


@rule
async def resolve_single_environment_name(
    request: SingleEnvironmentNameRequest,
) -> EnvironmentName:
    environment_names = await MultiGet(
        Get(EnvironmentName, EnvironmentNameRequest(name, request.description_of_origin))
        for name in request.raw_values
    )

    unique_environments = sorted({name.val or "<None>" for name in environment_names})
    if len(unique_environments) != 1:
        raise AssertionError(
            f"Needed 1 unique environment, but {request.description_of_origin} contained "
            f"{len(unique_environments)}:\n\n"
            f"{bullet_list(unique_environments)}"
        )
    return environment_names[0]


async def _apply_fallback_environment(env_tgt: Target, error_msg: str) -> EnvironmentName:
    fallback_field = env_tgt[FallbackEnvironmentField]
    if fallback_field.value is None:
        raise NoFallbackEnvironmentError(error_msg)
    return await Get(
        EnvironmentName,
        EnvironmentNameRequest(
            fallback_field.value,
            description_of_origin=(
                f"the `{fallback_field.alias}` field of the target {env_tgt.address}"
            ),
        ),
    )


@rule
async def resolve_environment_name(
    request: EnvironmentNameRequest,
    environments_subsystem: EnvironmentsSubsystem,
    global_options: GlobalOptions,
) -> EnvironmentName:
    if request.raw_value == LOCAL_ENVIRONMENT_MATCHER:
        local_env_name = await Get(ChosenLocalEnvironmentName)
        return local_env_name.val
    if request.raw_value == LOCAL_WORKSPACE_ENVIRONMENT_MATCHER:
        local_workspace_env_name = await Get(ChosenLocalWorkspaceEnvironmentName)
        return local_workspace_env_name.val
    if request.raw_value not in environments_subsystem.names:
        raise UnrecognizedEnvironmentError(
            softwrap(
                f"""
                Unrecognized environment name `{request.raw_value}` from
                {request.description_of_origin}.

                The value must either be `{LOCAL_ENVIRONMENT_MATCHER}` or a name from the option
                `[environments-preview].names`: {sorted(environments_subsystem.names.keys())}
                """
            )
        )

    # Get the target so that we can apply the environment_fallback field, if relevant.
    env_tgt = await Get(EnvironmentTarget, EnvironmentName(request.raw_value))
    if env_tgt.val is None:
        raise AssertionError(f"EnvironmentTarget.val is None for the name `{request.raw_value}`")

    if (
        env_tgt.val.has_field(RemoteFallbackEnvironmentField)
        and not global_options.remote_execution
    ):
        return await _apply_fallback_environment(
            env_tgt.val,
            error_msg=softwrap(
                f"""
                The global option `--remote-execution` is set to false, but the remote
                environment `{request.raw_value}` is used in {request.description_of_origin}.

                Either enable the option `--remote-execution`, or set the field
                `{FallbackEnvironmentField.alias}` for the target {env_tgt.val.address}.
                """
            ),
        )

    localhost_platform = Platform.create_for_localhost().value

    if env_tgt.val.has_field(DockerFallbackEnvironmentField):
        if not global_options.docker_execution:
            return await _apply_fallback_environment(
                env_tgt.val,
                error_msg=softwrap(
                    f"""
                    The global option `--docker-execution` is set to false, but the Docker
                    environment `{request.raw_value}` is used in {request.description_of_origin}.

                    Either enable the option `--docker-execution`, or set the field
                    `{FallbackEnvironmentField.alias}` for the target {env_tgt.val.address}.
                    """
                ),
            )

        if (
            localhost_platform in (Platform.linux_x86_64.value, Platform.linux_arm64.value)
            and localhost_platform != env_tgt.val[DockerPlatformField].normalized_value.value
        ):
            return await _apply_fallback_environment(
                env_tgt.val,
                error_msg=softwrap(
                    f"""
                    The Docker environment `{request.raw_value}` is specified in
                    {request.description_of_origin}, but it cannot be used because the local host has
                    the platform `{localhost_platform}` and the Docker environment has the platform
                    {env_tgt.val[DockerPlatformField].normalized_value}.

                    Consider setting the field `{FallbackEnvironmentField.alias}` for the target
                    {env_tgt.val.address}, such as to a `docker_environment` target that sets
                    `{DockerPlatformField.alias}` to `{localhost_platform}`. Alternatively, consider
                    not explicitly setting the field `{DockerPlatformField.alias}` for the target
                    {env_tgt.val.address} because the default behavior is to use the CPU architecture
                    of the current host for the platform (although this requires that the docker image
                    supports that CPU architecture).
                    """
                ),
            )

    if (
        env_tgt.val.has_field(LocalFallbackEnvironmentField)
        and localhost_platform not in env_tgt.val[CompatiblePlatformsField].value
    ):
        return await _apply_fallback_environment(
            env_tgt.val,
            error_msg=softwrap(
                f"""
                The local environment `{request.raw_value}` was specified in
                {request.description_of_origin}, but it is not compatible with the current
                machine's platform: {localhost_platform}. The environment only works with the
                platforms: {env_tgt.val[CompatiblePlatformsField].value}

                Consider setting the field `{FallbackEnvironmentField.alias}` for the target
                {env_tgt.val.address}, such as to a `docker_environment` or `remote_environment`
                target. You can also set that field to another `local_environment` target, such as
                one that is compatible with the current platform {localhost_platform}.
                """
            ),
        )

    return EnvironmentName(request.raw_value)


@rule
async def get_target_for_environment_name(
    env_name: EnvironmentName, environments_subsystem: EnvironmentsSubsystem
) -> EnvironmentTarget:
    if env_name.val is None:
        return EnvironmentTarget(None, None)
    if env_name.val not in environments_subsystem.names:
        raise AssertionError(
            softwrap(
                f"""
                The name `{env_name.val}` is not defined. The name should have been normalized and
                validated in the rule `EnvironmentNameRequest -> EnvironmentName`
                already. If you directly wrote
                `Get(EnvironmentTarget, EnvironmentName(my_name))`, refactor to
                `Get(EnvironmentTarget, EnvironmentNameRequest(my_name, ...))`.
                """
            )
        )
    _description_of_origin = "the option [environments-preview].names"
    address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(
            environments_subsystem.names[env_name.val], description_of_origin=_description_of_origin
        ),
    )
    wrapped_target = await Get(
        WrappedTargetForBootstrap,
        WrappedTargetRequest(address, description_of_origin=_description_of_origin),
    )
    tgt = wrapped_target.val
    if (
        not tgt.has_field(CompatiblePlatformsField)
        and not tgt.has_field(DockerImageField)
        and not tgt.has_field(RemotePlatformField)
    ):
        raise ValueError(
            softwrap(
                f"""
                Expected to use the address to a `local_environment`, `docker_environment`,
                `remote_environment`, or `workspace_environment` target in the option `[environments-preview].names`,
                but the name `{env_name.val}` was set to the target {address.spec} with the target type
                `{tgt.alias}`.
                """
            )
        )
    return EnvironmentTarget(env_name.val, tgt)


async def _maybe_add_docker_image_id(image_name: str, platform: Platform, address: Address) -> str:
    # If the image name appears to be just an image ID, just return it as-is.
    if image_name.startswith("sha256:"):
        return image_name

    # If the image name contains an appended image ID, then use it.
    if "@" in image_name:
        image_name_part, _, maybe_image_id = image_name.rpartition("@")
        if not maybe_image_id.startswith("sha256:"):
            raise ValueError(
                f"The Docker image `{image_name}` from the field {DockerImageField.alias} "
                f"for the target {address} contains what appears to be an image ID component, "
                "but does not appear to be the expected SHA-256 hash for an image."
            )
        return image_name

    # Otherwise, resolve the image name to an image ID and append the applicable component to the image name.
    resolve_result = await Get(
        DockerResolveImageResult,
        DockerResolveImageRequest(
            image_name=image_name,
            platform=platform.name,
        ),
    )

    # TODO(17104): Consider appending the correct image ID to the existing image name so error messages about the
    # image have context for the user. Note: The image ID used for a "repo digest" (tag and image ID) is not
    # the same as just the image's ID.
    return resolve_result.image_id


@rule
async def extract_process_config_from_environment(
    tgt: EnvironmentTarget,
    platform: Platform,
    global_options: GlobalOptions,
    environments_subsystem: EnvironmentsSubsystem,
) -> ProcessExecutionEnvironment:
    docker_image = None
    remote_execution = False
    raw_remote_execution_extra_platform_properties: tuple[str, ...] = ()
    execute_in_workspace = False

    if environments_subsystem.remote_execution_used_globally(global_options):
        remote_execution = True
        raw_remote_execution_extra_platform_properties = (
            global_options.remote_execution_extra_platform_properties
        )

    elif tgt.val is not None:
        docker_image = (
            tgt.val[DockerImageField].value if tgt.val.has_field(DockerImageField) else None
        )

        # If a docker image name is provided, convert to an image ID so caching works properly.
        # TODO(17104): Append image ID instead to the image name.
        if docker_image is not None:
            docker_image = await _maybe_add_docker_image_id(docker_image, platform, tgt.val.address)

        remote_execution = tgt.val.has_field(RemotePlatformField)
        if remote_execution:
            raw_remote_execution_extra_platform_properties = tgt.val[
                RemoteExtraPlatformPropertiesField
            ].value
            if global_options.remote_execution_extra_platform_properties:
                logger.warning(
                    softwrap(
                        f"""\
                        The option `[GLOBAL].remote_execution_extra_platform_properties` is set, but
                        it is ignored because you are using the environments target mechanism.
                        Instead, delete that option and set the field
                        `{RemoteExtraPlatformPropertiesField}.alias` on
                        `{RemoteEnvironmentTarget.alias}` targets.
                        """
                    )
                )

        execute_in_workspace = tgt.val.has_field(LocalWorkspaceCompatiblePlatformsField)

    return ProcessExecutionEnvironment(
        environment_name=tgt.name,
        platform=platform.value,
        docker_image=docker_image,
        remote_execution=remote_execution,
        remote_execution_extra_platform_properties=[
            tuple(pair.split("=", maxsplit=1))  # type: ignore[misc]
            for pair in raw_remote_execution_extra_platform_properties
        ],
        execute_in_workspace=execute_in_workspace,
    )


class _EnvironmentSensitiveOptionFieldMixin:
    subsystem: ClassVar[type[Subsystem.EnvironmentAware]]
    option_name: ClassVar[str]


class ShellStringSequenceField(StringSequenceField):
    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Optional[Tuple[str, ...]]:
        """Computes a flattened shlexed arg list from an iterable of strings."""
        if not raw_value:
            return ()

        return tuple(arg for raw_arg in raw_value for arg in shlex.split(raw_arg))


# Maps between non-list option value types and corresponding fields
_SIMPLE_OPTIONS: dict[Union[Type, Callable[[str], Any]], Type[Field]] = {
    str: StringField,
}

# Maps between the member types for list options. Each element is the
# field type, and the `value` type for the field.
_LIST_OPTIONS: dict[Union[Type, Callable[[str], Any]], Type[Field]] = {
    str: StringSequenceField,
    custom_types.shell_str: ShellStringSequenceField,
}


@memoized
def add_option_fields_for(env_aware: type[Subsystem.EnvironmentAware]) -> Iterable[UnionRule]:
    """Register environment fields for the options declared in `env_aware`

    This is called by `env_aware.subsystem.rules()`, which is called whenever a rule depends on
    `env_aware`. It will register the relevant fields under the `local_environment` and
    `docker_environment` targets. Note that it must be `memoized`, such that repeated calls result
    in exactly the same rules being registered.
    """

    field_rules: set[UnionRule] = set()

    for option in collect_options_info(env_aware):
        field_rules.update(_add_option_field_for(env_aware, option))

    return field_rules


def option_field_name_for(flag_names: Sequence[str]) -> str:
    return flag_names[0][2:].replace("-", "_")


def _add_option_field_for(
    env_aware_t: type[Subsystem.EnvironmentAware],
    option: OptionsInfo,
) -> Iterable[UnionRule]:
    option_type: type = option.flag_options["type"]
    scope = env_aware_t.subsystem.options_scope

    snake_name = option_field_name_for(option.flag_names)

    # Note that there is not presently good support for enum options. `str`-backed enums should
    # be easy enough to add though...

    if option_type != list:
        try:
            field_type = _SIMPLE_OPTIONS[option_type]
        except KeyError:
            raise AssertionError(
                f"The option `[{scope}].{snake_name}` has a value type that does not yet have a "
                "mapping in `environments.py`. To fix, map the value type in `_SIMPLE_OPTIONS` "
                "to a `Field` subtype that supports your option's value type."
            )
    else:
        member_type = option.flag_options["member_type"]
        try:
            field_type = _LIST_OPTIONS[member_type]
        except KeyError:
            raise AssertionError(
                f"The option `[{scope}].{snake_name}` has a member value type that does yet have "
                "a mapping in `environments.py`. To fix, map the member value type in "
                "`_LIST_OPTIONS` to a `SequenceField` subtype that supports your option's member "
                "value type."
            )

    # The below class will never be used for static type checking outside of this function.
    # so it's reasonably safe to use `ignore[name-defined]`. Ensure that all this remains valid
    # if `_SIMPLE_OPTIONS` or `_LIST_OPTIONS` are ever modified.
    class OptionField(field_type, _EnvironmentSensitiveOptionFieldMixin):  # type: ignore[valid-type, misc]
        alias = f"{scope}_{snake_name}".replace("-", "_")
        required = False
        value: Any
        help = (
            f"Overrides the default value from the option `[{scope}].{snake_name}` when this "
            "environment target is active."
        )
        subsystem = env_aware_t
        option_name = option.flag_names[0]

    setattr(OptionField, "__qualname__", f"{option_type.__qualname__}.{OptionField.__name__}")

    return [
        LocalEnvironmentTarget.register_plugin_field(OptionField),
        LocalWorkspaceEnvironmentTarget.register_plugin_field(OptionField),
        DockerEnvironmentTarget.register_plugin_field(OptionField),
        RemoteEnvironmentTarget.register_plugin_field(OptionField),
    ]


def resolve_environment_sensitive_option(name: str, subsystem: Subsystem.EnvironmentAware):
    """Return the value from the environment field corresponding to the scope and name provided.

    If not defined, return `None`.
    """

    env_tgt = subsystem.env_tgt

    if env_tgt.val is None:
        return None

    options = _options(env_tgt)

    maybe = options.get((type(subsystem), name))
    if maybe is None or maybe.value is None:
        return None
    else:
        return maybe.value


@memoized
def _options(
    env_tgt: EnvironmentTarget,
) -> dict[tuple[type[Subsystem.EnvironmentAware], str], Field]:
    """Index the environment-specific `fields` on an environment target by subsystem and name."""

    options: dict[tuple[type[Subsystem.EnvironmentAware], str], Field] = {}

    if env_tgt.val is None:
        return options

    for _, field in env_tgt.val.field_values.items():
        if isinstance(field, _EnvironmentSensitiveOptionFieldMixin):
            options[(field.subsystem, field.option_name)] = field

    return options


def rules():
    return (
        *collect_rules(),
        UnionRule(FieldDefaultFactoryRequest, DockerPlatformFieldDefaultFactoryRequest),
        QueryRule(ChosenLocalEnvironmentName, []),
    )
