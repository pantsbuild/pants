# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.build_graph.address import Address, AddressInput
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
from pants.util.memo import memoized_property
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
    _platforms_to_local_environment = DictOption[str](
        help=softwrap(
            """
            A mapping of platform strings to addresses to `_local_environment` targets. For example:

                [environments-preview.platforms_to_local_environment]
                linux_arm64 = "//:linux_arm64_environment"
                linux_x86_64 = "//:linux_x86_environment"
                macos_arm64 = "//:macos_environment"
                macos_x86_64 = "//:macos_environment"

            Pants will detect what platform you are currently on and load the specified
            environment. If a platform is not defined, then Pants will use legacy options like
            `[python-bootstrap].search_path`.

            Warning: this feature is experimental and this option may be changed and removed before
            the first 2.15 alpha release.
            """
        )
    )

    @memoized_property
    def platforms_to_local_environment(self) -> dict[str, str]:
        valid_platforms = {plat.value for plat in Platform}
        invalid_keys = set(self._platforms_to_local_environment.keys()) - valid_platforms
        if invalid_keys:
            raise ValueError(
                softwrap(
                    f"""
                    Unrecognized platforms as the keys to the option
                    `[environments-preview].platforms_to_local_environment`: {sorted(invalid_keys)}

                    All valid platforms: {sorted(valid_platforms)}
                    """
                )
            )
        return self._platforms_to_local_environment


# -------------------------------------------------------------------------------------------
# Environment targets
# -------------------------------------------------------------------------------------------


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


class AllEnvironments(FrozenDict[str, LocalEnvironmentTarget]):
    """A mapping of environment aliases to their corresponding environment target."""


@dataclass(frozen=True)
class ChosenLocalEnvironment:
    tgt: LocalEnvironmentTarget | None


@rule
async def determine_all_environments(
    environments_subsystem: EnvironmentsSubsystem,
) -> AllEnvironments:
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
    return AllEnvironments(
        {
            alias: wrapped_tgt.target
            for alias, wrapped_tgt in zip(environments_subsystem.aliases.keys(), wrapped_targets)
        }
    )


@rule
async def choose_local_environment(
    platform: Platform, environments_subsystem: EnvironmentsSubsystem
) -> ChosenLocalEnvironment:
    raw_address = environments_subsystem.platforms_to_local_environment.get(platform.value)
    if not raw_address:
        return ChosenLocalEnvironment(None)
    _description_of_origin = "the option [environments-preview].platforms_to_local_environment"
    address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(raw_address, description_of_origin=_description_of_origin),
    )
    wrapped_target = await Get(
        WrappedTarget, WrappedTargetRequest(address, description_of_origin=_description_of_origin)
    )
    # TODO(#7735): this is not idiomatic to check for the target subclass.
    if not isinstance(wrapped_target.target, LocalEnvironmentTarget):
        raise ValueError(
            softwrap(
                f"""
                Expected to use the address to a `_local_environment` target in the option
                `[environments-preview].platforms_to_local_environment`, but the platform
                `{platform.value}` was set to the target {address} with the target type
                `{wrapped_target.target.alias}`.
                """
            )
        )
    return ChosenLocalEnvironment(wrapped_target.target)


def rules():
    return collect_rules()
