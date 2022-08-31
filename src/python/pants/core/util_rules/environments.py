# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pants.build_graph.address import Address, AddressInput
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.platform import Platform
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    StringSequenceField,
    Target,
    WrappedTarget,
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

    aliases = DictOption[str](
        help=softwrap(
            """
            A mapping of logical names to addresses to `_local_environment` targets. For example:

                [environments-preview.aliases]
                linux_local = "//:linux_env"
                macos_local = "//:macos_env"
                linux_ci = "build-support:linux_ci_env"
                macos_ci = "build-support:macos_ci_env"

            TODO(#7735): explain how aliases are used once they are consumed.

            Pants will ignore any environment targets that are not given an alias via this option.
            """
        )
    )


# -------------------------------------------------------------------------------------------
# Environment targets
# -------------------------------------------------------------------------------------------

LOCAL_ENVIRONMENT_MATCHER = "__local__"


class CompatiblePlatformsField(StringSequenceField):
    alias = "compatible_platforms"
    default = tuple(plat.value for plat in Platform)
    valid_choices = Platform
    value: tuple[str, ...]
    help = softwrap(
        """
        Which platforms this environment can be used with.

        This is used for Pants to automatically determine which which environment target to use for
        the user's machine. Currently, there must be exactly one environment target for the
        platform.
        """
    )


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


class LocalEnvironmentTarget(Target):
    alias = "_local_environment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CompatiblePlatformsField,
        PythonInterpreterSearchPathsField,
        PythonBootstrapBinaryNamesField,
    )
    help = softwrap(
        """
        Configuration of environment variables and search paths for running Pants locally.

        TODO(#7735): Explain how this gets used once we settle on the modeling.
        """
    )


# -------------------------------------------------------------------------------------------
# Rules
# -------------------------------------------------------------------------------------------


class NoCompatibleEnvironmentError(Exception):
    pass


class AmbiguousEnvironmentError(Exception):
    pass


class UnrecognizedEnvironmentError(Exception):
    pass


class AllEnvironmentTargets(FrozenDict[str, LocalEnvironmentTarget]):
    """A mapping of environment aliases to their corresponding environment target."""


@dataclass(frozen=True)
class ChosenLocalEnvironmentAlias:
    f"""Which environment alias from `[environments-preview].aliases` that
    {LOCAL_ENVIRONMENT_MATCHER} resolves to."""

    val: str | None


@dataclass(frozen=True)
class ResolvedEnvironmentAlias(EngineAwareParameter):
    f"""The normalized alias for an environment, from `[environments-preview].aliases`, after
    applying things like {LOCAL_ENVIRONMENT_MATCHER}.

    Note that we have this type, rather than only `ResolvedEnvironmentTarget`, for a more efficient
    rule graph. This node impacts the equality of many downstream nodes, so we want its identity
    to only be a single string, rather than a Target instance.
    """

    val: str | None

    def debug_hint(self) -> str:
        return self.val or "<none>"


@dataclass(frozen=True)
class ResolvedEnvironmentTarget:
    val: LocalEnvironmentTarget | None


@dataclass(frozen=True)
class ResolvedEnvironmentRequest(EngineAwareParameter):
    f"""Normalize the value into an alias from `[environments-preview].aliases`, such as by
    applying {LOCAL_ENVIRONMENT_MATCHER}."""

    raw_value: str
    description_of_origin: str

    def debug_hint(self) -> str:
        return self.raw_value


@rule
async def determine_all_environments(
    environments_subsystem: EnvironmentsSubsystem,
) -> AllEnvironmentTargets:
    _description_of_origin = "the option [environments-preview].aliases"
    addresses = await MultiGet(
        Get(
            Address,
            AddressInput,
            AddressInput.parse(raw_address, description_of_origin=_description_of_origin),
        )
        for raw_address in environments_subsystem.aliases.values()
    )
    wrapped_targets = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(address, description_of_origin=_description_of_origin),
        )
        for address in addresses
    )
    # TODO(#7735): validate the correct target type is used?
    return AllEnvironmentTargets(
        (alias, cast(LocalEnvironmentTarget, wrapped_tgt.target))
        for alias, wrapped_tgt in zip(environments_subsystem.aliases.keys(), wrapped_targets)
    )


@rule
async def determine_local_environment(
    platform: Platform, all_environment_targets: AllEnvironmentTargets
) -> ChosenLocalEnvironmentAlias:
    if not all_environment_targets:
        return ChosenLocalEnvironmentAlias(None)
    compatible_alias_and_targets = [
        (alias, tgt)
        for alias, tgt in all_environment_targets.items()
        if platform.value in tgt[CompatiblePlatformsField].value
    ]
    if not compatible_alias_and_targets:
        raise NoCompatibleEnvironmentError(
            softwrap(
                f"""
                No `_local_environment` targets from `[environments-preview].aliases` are
                compatible with the current platform: {platform.value}

                To fix, either adjust the `{CompatiblePlatformsField.alias}` field from the targets
                in `[environments-preview].aliases` to include `{platform.value}`, or define a new
                `_local_environment` target with `{platform.value}` included in the
                `{CompatiblePlatformsField.alias}` field. (Current targets from
                `[environments-preview].aliases`:
                {sorted(tgt.address.spec for tgt in all_environment_targets.values())})
                """
            )
        )
    elif len(compatible_alias_and_targets) > 1:
        # TODO(#7735): Allow the user to disambiguate what __local__ means via an option.
        raise AmbiguousEnvironmentError(
            softwrap(
                f"""
                Multiple `_local_environment` targets from `[environments-preview].aliases`
                are compatible with the current platform `{platform.value}`, so it is ambiguous
                which to use:
                {sorted(tgt.address.spec for _alias, tgt in compatible_alias_and_targets)}

                To fix, either adjust the `{CompatiblePlatformsField.alias}` field from those
                targets so that only one includes the value `{platform.value}`, or change
                `[environments-preview].aliases` so that it does not define some of those targets.
                """
            )
        )
    result_alias, _tgt = compatible_alias_and_targets[0]
    return ChosenLocalEnvironmentAlias(result_alias)


@rule
async def resolve_environment_alias(
    request: ResolvedEnvironmentRequest, environments_subsystem: EnvironmentsSubsystem
) -> ResolvedEnvironmentAlias:
    if request.raw_value == LOCAL_ENVIRONMENT_MATCHER:
        local_env_alias = await Get(ChosenLocalEnvironmentAlias, {})
        return ResolvedEnvironmentAlias(local_env_alias.val)
    if request.raw_value not in environments_subsystem.aliases:
        raise UnrecognizedEnvironmentError(
            softwrap(
                f"""
                Unrecognized environment alias `{request.raw_value}` from
                {request.description_of_origin}.

                The value must either be `{LOCAL_ENVIRONMENT_MATCHER}` or an alias from the option
                `[environments-preview].aliases`: {sorted(environments_subsystem.aliases.keys())}
                """
            )
        )
    return ResolvedEnvironmentAlias(request.raw_value)


@rule
def get_target_for_environment_alias(
    alias: ResolvedEnvironmentAlias, all_targets: AllEnvironmentTargets
) -> ResolvedEnvironmentTarget:
    if alias.val is None:
        return ResolvedEnvironmentTarget(None)
    if alias.val not in all_targets:
        raise AssertionError(
            softwrap(
                f"""
                The alias `{alias.val}` is not defined. The alias should have been normalized and
                validated in the rule `ResolvedEnvironmentRequest -> ResolvedEnvironmentAlias`
                already. If you directly wrote
                `Get(ResolvedEnvironmentTarget, ResolvedEnvironmentAlias(my_alias))`, refactor to
                `Get(ResolvedEnvironmentTarget, ResolvedEnvironmentRequest(my_alias, ...))`.
                """
            )
        )
    return ResolvedEnvironmentTarget(all_targets[alias.val])


def rules():
    return collect_rules()
