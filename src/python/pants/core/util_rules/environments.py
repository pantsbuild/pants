# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, cast

from pants.build_graph.address import Address, AddressInput
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.environment import EnvironmentName as EnvironmentName
from pants.engine.internals.graph import WrappedTargetForBootstrap
from pants.engine.internals.native_engine import ProcessConfigFromEnvironment
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.platform import Platform
from pants.engine.rules import Get, MultiGet, QueryRule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
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
from pants.option.global_options import GlobalOptions
from pants.option.option_types import DictOption, OptionsInfo, _collect_options_info_extended
from pants.option.subsystem import Subsystem
from pants.util.enums import match
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized
from pants.util.strutil import softwrap


class EnvironmentsSubsystem(Subsystem):
    options_scope = "environments-preview"
    help = softwrap(
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

            TODO(#7735): explain how names are used once they are consumed.

            Pants will ignore any environment targets that are not given a name via this option.
            """
        )
    )


# -------------------------------------------------------------------------------------------
# Environment targets
# -------------------------------------------------------------------------------------------

LOCAL_ENVIRONMENT_MATCHER = "__local__"


class EnvironmentField(StringField):
    alias = "_environment"
    default = LOCAL_ENVIRONMENT_MATCHER
    value: str
    help = softwrap(
        """
        TODO(#7735): fill this in.
        """
    )


class CompatiblePlatformsField(StringSequenceField):
    alias = "compatible_platforms"
    default = tuple(plat.value for plat in Platform)
    valid_choices = Platform
    value: tuple[str, ...]
    help = softwrap(
        """
        Which platforms this environment can be used with.

        This is used for Pants to automatically determine which environment target to use for
        the user's machine. Currently, there must be exactly one environment target for the
        platform.
        """
    )


class LocalEnvironmentTarget(Target):
    alias = "_local_environment"
    core_fields = (*COMMON_TARGET_FIELDS, CompatiblePlatformsField)
    help = softwrap(
        """
        Configuration of environment variables and search paths for running Pants locally.

        TODO(#7735): Explain how this gets used once we allow targets to set environment.
        """
    )


class DockerImageField(StringField):
    alias = "image"
    required = True
    value: str
    help = softwrap(
        """
        The docker image ID to use when this environment is loaded, e.g. `centos6:latest`.

        TODO: expectations about what are valid IDs, e.g. if they must come from DockerHub vs other
        registries.
        """
    )


class DockerPlatformField(StringField):
    alias = "platform"
    default = None
    valid_choices = Platform
    help = softwrap(
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


class DockerEnvironmentTarget(Target):
    alias = "_docker_environment"
    core_fields = (*COMMON_TARGET_FIELDS, DockerImageField, DockerPlatformField)
    help = softwrap(
        """
        Configuration of a Docker image used for building your code, including the environment
        variables and search paths used by Pants.

        TODO(#7735): Explain how this gets used once we allow targets to set environment.
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
    help = softwrap(
        """
        Platform properties to set on remote execution requests.

        Format: property=value. Multiple values should be specified as multiple
        occurrences of this flag.

        Pants itself may add additional platform properties.
        """
    )


class RemoteEnvironmentTarget(Target):
    alias = "_remote_environment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RemotePlatformField,
        RemoteExtraPlatformPropertiesField,
    )
    help = softwrap(
        """
        Configuration of a remote execution environment used for building your code, including the
        environment variables and search paths used by Pants.

        Note that you must also configure remote execution with the global options like
        `remote_execution` and `remote_execution_address`.

        Often, it is only necessary to have a single `_remote_environment` target for your
        repository, but it can be useful to have >1 so that you can set different
        `extra_platform_properties`. For example, with some servers, you could use this to
        configure a different Docker image per environment.
        """
    )


# -------------------------------------------------------------------------------------------
# Rules
# -------------------------------------------------------------------------------------------


def determine_bootstrap_environment(session: SchedulerSession) -> EnvironmentName:
    local_env = cast(
        ChosenLocalEnvironmentName,
        session.product_request(ChosenLocalEnvironmentName, [Params()])[0],
    )
    return EnvironmentName(local_env.val)


class NoCompatibleEnvironmentError(Exception):
    pass


class AmbiguousEnvironmentError(Exception):
    pass


class UnrecognizedEnvironmentError(Exception):
    pass


class AllEnvironmentTargets(FrozenDict[str, Target]):
    """A mapping of environment names to their corresponding environment target."""


@dataclass(frozen=True)
class ChosenLocalEnvironmentName:
    """Which environment name from `[environments-preview].names` that __local__ resolves to."""

    val: str | None


@dataclass(frozen=True)
class EnvironmentTarget:
    val: Target | None


@dataclass(frozen=True)
class EnvironmentNameRequest(EngineAwareParameter):
    f"""Normalize the value into a name from `[environments-preview].names`, such as by
    applying {LOCAL_ENVIRONMENT_MATCHER}."""

    raw_value: str
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

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
        for attr in dir(field_set):
            # Skip what look like dunder methods, which are unlikely to be an
            # EnvironmentField value on FieldSet class declarations.
            if attr.startswith("__"):
                continue
            val = getattr(field_set, attr)
            if isinstance(val, EnvironmentField):
                env_field = val
                break
        else:
            env_field = EnvironmentField(None, address=field_set.address)

        return EnvironmentNameRequest(
            env_field.value,
            # Note that if the field was not registered, we will have fallen back to the default
            # LOCAL_ENVIRONMENT_MATCHER, which we expect to be infallible when normalized. That
            # implies that the error message using description_of_origin should not trigger, so
            # it's okay that the field is not actually registered on the target.
            description_of_origin=(
                f"the `{env_field.alias}` field from the target {field_set.address}"
            ),
        )

    def debug_hint(self) -> str:
        return self.raw_value


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
    if not all_environment_targets:
        return ChosenLocalEnvironmentName(None)
    compatible_name_and_targets = [
        (name, tgt)
        for name, tgt in all_environment_targets.items()
        if tgt.has_field(CompatiblePlatformsField)
        and platform.value in tgt[CompatiblePlatformsField].value
    ]
    if not compatible_name_and_targets:
        raise NoCompatibleEnvironmentError(
            softwrap(
                f"""
                No `_local_environment` targets from `[environments-preview].names` are
                compatible with the current platform: {platform.value}

                To fix, either adjust the `{CompatiblePlatformsField.alias}` field from the targets
                in `[environments-preview].names` to include `{platform.value}`, or define a new
                `_local_environment` target with `{platform.value}` included in the
                `{CompatiblePlatformsField.alias}` field. (Current targets from
                `[environments-preview].names`:
                {sorted(tgt.address.spec for tgt in all_environment_targets.values())})
                """
            )
        )
    elif len(compatible_name_and_targets) > 1:
        # TODO(#7735): Consider if we still want to error when no target is found, given that we
        #  are now falling back to subsystem values.
        # TODO(#7735): Allow the user to disambiguate what __local__ means via an option.
        raise AmbiguousEnvironmentError(
            softwrap(
                f"""
                Multiple `_local_environment` targets from `[environments-preview].names`
                are compatible with the current platform `{platform.value}`, so it is ambiguous
                which to use:
                {sorted(tgt.address.spec for _name, tgt in compatible_name_and_targets)}

                To fix, either adjust the `{CompatiblePlatformsField.alias}` field from those
                targets so that only one includes the value `{platform.value}`, or change
                `[environments-preview].names` so that it does not define some of those targets.
                """
            )
        )
    result_name, _tgt = compatible_name_and_targets[0]
    return ChosenLocalEnvironmentName(result_name)


@rule
async def resolve_environment_name(
    request: EnvironmentNameRequest, environments_subsystem: EnvironmentsSubsystem
) -> EnvironmentName:
    if request.raw_value == LOCAL_ENVIRONMENT_MATCHER:
        local_env_name = await Get(ChosenLocalEnvironmentName, {})
        return EnvironmentName(local_env_name.val)
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
    return EnvironmentName(request.raw_value)


@rule
async def get_target_for_environment_name(
    env_name: EnvironmentName, environments_subsystem: EnvironmentsSubsystem
) -> EnvironmentTarget:
    if env_name.val is None:
        return EnvironmentTarget(None)
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
    if not tgt.has_field(CompatiblePlatformsField) and not tgt.has_field(DockerImageField):
        raise ValueError(
            softwrap(
                f"""
                Expected to use the address to a `_local_environment` or `_docker_environment`
                target in the option `[environments-preview].names`, but the name
                `{env_name.val}` was set to the target {address.spec} with the target type
                `{tgt.alias}`.
                """
            )
        )
    return EnvironmentTarget(tgt)


@rule
def extract_process_config_from_environment(
    tgt: EnvironmentTarget, platform: Platform, global_options: GlobalOptions
) -> ProcessConfigFromEnvironment:
    if tgt.val is None:
        docker_image = None
        remote_execution = global_options.remote_execution
        raw_remote_execution_extra_platform_properties = (
            global_options.remote_execution_extra_platform_properties if remote_execution else ()
        )
    else:
        docker_image = (
            tgt.val[DockerImageField].value if tgt.val.has_field(DockerImageField) else None
        )
        remote_execution = tgt.val.has_field(RemotePlatformField)
        if remote_execution:
            raw_remote_execution_extra_platform_properties = tgt.val[
                RemoteExtraPlatformPropertiesField
            ].value
            if global_options.remote_execution_extra_platform_properties:
                logging.warning(
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
        else:
            raw_remote_execution_extra_platform_properties = ()

    return ProcessConfigFromEnvironment(
        platform=platform.value,
        docker_image=docker_image,
        remote_execution=remote_execution,
        remote_execution_extra_platform_properties=[
            tuple(pair.split("=", maxsplit=1))  # type: ignore[misc]
            for pair in raw_remote_execution_extra_platform_properties
        ],
    )


class EnvironmentSensitiveOptionFieldMixin:
    subsystem: ClassVar[type[Subsystem.EnvironmentAware]]
    option_name: ClassVar[str]


# Maps between non-list option value types and corresponding fields
_SIMPLE_OPTIONS: dict[type, type[Field]] = {
    str: StringField,
}

# Maps between the member types for list options. Each element is the
# field type, and the `value` type for the field.
_LIST_OPTIONS: dict[type, type[Field]] = {
    str: StringSequenceField,
}


@memoized
def add_option_fields_for(subsystem: type[Subsystem]) -> Iterable[UnionRule]:
    """Register environment fields for the `environment_sensitive` options of `subsystem`

    This should be called in the `rules()` method in the file where `subsystem` is defined. It will
    register the relevant fields under the `local_environment` and `docker_environment` targets.
    """
    field_rules: set[UnionRule] = set()

    for option_attrname, option in _collect_options_info_extended(subsystem.EnvironmentAware):
        if option.flag_options["environment_sensitive"]:
            field_rules.update(
                _add_option_field_for(
                    subsystem, subsystem.EnvironmentAware, option, option_attrname
                )
            )

    return field_rules


def _add_option_field_for(
    subsystem_t: type[Subsystem],
    env_aware_t: type[Subsystem.EnvironmentAware],
    option: OptionsInfo,
    attrname: str,
) -> Iterable[UnionRule]:
    option_type: type = option.flag_options["type"]
    scope = subsystem_t.options_scope

    # Note that there is not presently good support for enum options. `str`-backed enums should
    # be easy enough to add though...

    if option_type != list:
        try:
            field_type = _SIMPLE_OPTIONS[option_type]
        except KeyError:
            raise AssertionError(
                f"The option `{subsystem_t.__name__}.EnvironmentAware.{attrname}` has a value type that does "
                "not yet have a mapping in `environments.py`. To fix, map the value type in "
                "`_SIMPLE_OPTIONS` to a `Field` subtype that supports your option's value type."
            )
    else:
        member_type = option.flag_options["member_type"]
        try:
            field_type = _LIST_OPTIONS[member_type]
        except KeyError:
            raise AssertionError(
                f"The option `{subsystem_t.__name__}.EnvironmentAware.{attrname}` has a member value type that "
                "does yet have a mapping in `environments.py`. To fix, map the member value type "
                "in `_LIST_OPTIONS` to a `SequenceField` subtype that supports your option's "
                "member value type."
            )

    # The below class will never be used for static type checking outside of this function.
    # so it's reasonably safe to use `ignore[name-defined]`. Ensure that all this remains valid
    # if `_SIMPLE_OPTIONS` or `_LIST_OPTIONS` are ever modified.
    class OptionField(field_type, EnvironmentSensitiveOptionFieldMixin):  # type: ignore[valid-type, misc]
        # TODO: use envvar-like normalization logic here
        alias = f"{scope}_{option.flag_names[0][2:]}".replace("-", "_")
        required = False
        value: Any
        help = (
            f"Overrides the default value from the option `[{scope}].{attrname}` when this "
            "environment target is active."
        )
        subsystem = env_aware_t
        option_name = attrname

    return [
        LocalEnvironmentTarget.register_plugin_field(OptionField),
        DockerEnvironmentTarget.register_plugin_field(OptionField),
        RemoteEnvironmentTarget.register_plugin_field(OptionField),
    ]


def get_option(name: str, subsystem: Subsystem.EnvironmentAware):
    """Get the option from the `EnvionmentTarget`, if specified there, else from the `Subsystem`.

    This is slated for quick deprecation once we can construct `Subsystems` per environment.
    """

    env_tgt = subsystem.env_tgt

    if env_tgt.val is None:
        return getattr(subsystem, name)

    options = _options(env_tgt)

    maybe = options.get((type(subsystem), name))
    if maybe is None or maybe.value is None:
        return subsystem.options[name]
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
        if isinstance(field, EnvironmentSensitiveOptionFieldMixin):
            options[(field.subsystem, field.option_name)] = field

    return options


def rules():
    return (
        *collect_rules(),
        UnionRule(FieldDefaultFactoryRequest, DockerPlatformFieldDefaultFactoryRequest),
        QueryRule(ChosenLocalEnvironmentName, []),
    )
