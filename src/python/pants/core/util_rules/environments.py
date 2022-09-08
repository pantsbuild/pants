# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import cast

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
    StringField,
    StringSequenceField,
    Target,
    WrappedTargetRequest,
)
from pants.option.option_types import DictOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
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


class PythonInterpreterSearchPathsField(StringSequenceField):
    alias = "python_interpreter_search_paths"
    default = ("<PYENV>", "<PATH>")
    value: tuple[str, ...]
    help = softwrap(
        """
        A list of paths to search for Python interpreters.

        Which interpreters are actually used from these paths is context-specific:
        the Python backend selects interpreters using options on the `python` subsystem,
        in particular, the `[python].interpreter_constraints` option.

        You can specify absolute paths to interpreter binaries
        and/or to directories containing interpreter binaries. The order of entries does
        not matter.

        The following special strings are supported:

          * `<PATH>`, the contents of the PATH env var
          * `<ASDF>`, all Python versions currently configured by ASDF \
              `(asdf shell, ${HOME}/.tool-versions)`, with a fallback to all installed versions
          * `<ASDF_LOCAL>`, the ASDF interpreter with the version in BUILD_ROOT/.tool-versions
          * `<PYENV>`, all Python versions under $(pyenv root)/versions
          * `<PYENV_LOCAL>`, the Pyenv interpreter with the version in BUILD_ROOT/.python-version
          * `<PEXRC>`, paths in the PEX_PYTHON_PATH variable in /etc/pexrc or ~/.pexrc
        """
    )


class PythonBootstrapBinaryNamesField(StringSequenceField):
    alias = "python_bootstrap_binary_names"
    default = ("python", "python3")
    value: tuple[str, ...]
    help = softwrap(
        f"""
        The names of Python binaries to search for. See the
        `{PythonInterpreterSearchPathsField.alias}` field to influence where interpreters are
        searched for.

        This does not impact which Python interpreter is used to run your code, only what
        is used to run internal tools.
        """
    )


_COMMON_ENV_FIELDS = (
    *COMMON_TARGET_FIELDS,
    PythonInterpreterSearchPathsField,
    PythonBootstrapBinaryNamesField,
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
    core_fields = (*_COMMON_ENV_FIELDS, CompatiblePlatformsField)
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


class DockerEnvironmentTarget(Target):
    alias = "_docker_environment"
    core_fields = (*_COMMON_ENV_FIELDS, DockerImageField)
    help = softwrap(
        """
        Configuration of a Docker image used for building your code, including the environment
        variables and search paths used by Pants.

        TODO(#7735): Explain how this gets used once we allow targets to set environment.
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
class EnvironmentRequest(EngineAwareParameter):
    f"""Normalize the value into a name from `[environments-preview].names`, such as by
    applying {LOCAL_ENVIRONMENT_MATCHER}."""

    raw_value: str
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

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
    request: EnvironmentRequest, environments_subsystem: EnvironmentsSubsystem
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
                validated in the rule `EnvironmentRequest -> EnvironmentName`
                already. If you directly wrote
                `Get(EnvironmentTarget, EnvironmentName(my_name))`, refactor to
                `Get(EnvironmentTarget, EnvironmentRequest(my_name, ...))`.
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
def extract_process_config_from_environment(tgt: EnvironmentTarget) -> ProcessConfigFromEnvironment:
    docker_image = (
        tgt.val[DockerImageField].value if tgt.val and tgt.val.has_field(DockerImageField) else None
    )
    return ProcessConfigFromEnvironment(docker_image=docker_image)


def rules():
    return (*collect_rules(), QueryRule(ChosenLocalEnvironmentName, []))
