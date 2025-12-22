# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.lint.first_party_plugins import (
    BaseFirstPartyPlugins,
    resolve_first_party_plugins,
)
from pants.backend.python.lint.flake8.skip_field import SkipFlake8Field
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.util_rules import python_sources
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileListOption,
    FileOption,
    SkipOption,
    TargetListOption,
)
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class Flake8FieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField
    resolve: PythonResolveField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipFlake8Field).value


class Flake8(PythonToolBase):
    options_scope = "flake8"
    name = "Flake8"
    help_short = "The Flake8 Python linter (https://flake8.pycqa.org/)."

    default_main = ConsoleScript("flake8")
    default_requirements = ["flake8>=5.0.4,<7"]

    default_lockfile_resource = ("pants.backend.python.lint.flake8", "flake8.lock")

    skip = SkipOption("lint")
    args = ArgsListOption(example="--ignore E123,W456 --enable-extensions H111")
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to an INI config file understood by Flake8
            (https://flake8.pycqa.org/en/latest/user/configuration.html).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    extra_files = FileListOption(
        default=None,
        advanced=True,
        help=softwrap(
            """Paths to extra files to include in the sandbox. This can be useful for Flake8 plugins,
            like including config files for the `flake8-bandit` plugin."""
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`.flake8`, `flake8`, `setup.cfg`, and `tox.ini`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )
    _source_plugins = TargetListOption(
        advanced=True,
        help=softwrap(
            f"""
            An optional list of `python_sources` target addresses to load first-party plugins.

            You must set the plugin's parent directory as a source root. For
            example, if your plugin is at `build-support/flake8/custom_plugin.py`, add
            `'build-support/flake8'` to `[source].root_patterns` in `pants.toml`. This is
            necessary for Pants to know how to tell Flake8 to discover your plugin. See
            {doc_url("docs/using-pants/key-concepts/source-roots")}

            You must also set `[flake8:local-plugins]` in your Flake8 config file.

            For example:

                [flake8:local-plugins]
                extension =
                CUSTOMCODE = custom_plugin:MyChecker

            While your plugin's code can depend on other first-party code and third-party
            requirements, all first-party dependencies of the plugin must live in the same
            directory or a subdirectory.

            To instead load third-party plugins, add them to a custom resolve alongside
            flake8 itself, as described in {doc_url("docs/python/overview/lockfiles#lockfiles-for-tools")}.
            """
        ),
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # See https://flake8.pycqa.org/en/latest/user/configuration.html#configuration-locations
        # for how Flake8 discovers config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=["flake8", ".flake8"],
            check_content={"setup.cfg": b"[flake8]", "tox.ini": b"[flake8]"},
        )

    @property
    def source_plugins(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(
            self._source_plugins,
            owning_address=None,
            description_of_origin=f"the option `[{self.options_scope}].source_plugins`",
        )


# --------------------------------------------------------------------------------------
# First-party plugins
# --------------------------------------------------------------------------------------


class Flake8FirstPartyPlugins(BaseFirstPartyPlugins):
    pass


@rule(desc="Prepare [flake8].source_plugins", level=LogLevel.DEBUG)
async def flake8_first_party_plugins(flake8: Flake8) -> Flake8FirstPartyPlugins:
    return await resolve_first_party_plugins(flake8.source_plugins, Flake8FirstPartyPlugins)


def rules():
    return (
        *collect_rules(),
        *python_sources.rules(),
        UnionRule(ExportableTool, Flake8),
    )
