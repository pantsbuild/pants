# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.lint.first_party_plugins import (
    BaseFirstPartyPlugins,
    resolve_first_party_plugins,
)
from pants.backend.python.lint.pylint.skip_field import SkipPylintField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    FileOption,
    SkipOption,
    TargetListOption,
)
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class PylintFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPylintField).value


# --------------------------------------------------------------------------------------
# Subsystem
# --------------------------------------------------------------------------------------


class Pylint(PythonToolBase):
    options_scope = "pylint"
    name = "Pylint"
    help_short = "The Pylint linter for Python code (https://www.pylint.org/)."

    default_main = ConsoleScript("pylint")
    default_requirements = ["pylint>=4.0.0,<5"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.10,<3.15"]

    default_lockfile_resource = ("pants.backend.python.lint.pylint", "pylint.lock")

    skip = SkipOption("lint")
    args = ArgsListOption(example="--ignore=foo.py,bar.py --disable=C0330,W0311")
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file understood by Pylint
            (http://pylint.pycqa.org/en/latest/user_guide/run.html#command-line-options).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`.pylintrc`, `pylintrc`, `pyproject.toml`, and `setup.cfg`).

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
            example, if your plugin is at `build-support/pylint/custom_plugin.py`, add
            `'build-support/pylint'` to `[source].root_patterns` in `pants.toml`. This is
            necessary for Pants to know how to tell Pylint to discover your plugin. See
            {doc_url("docs/using-pants/key-concepts/source-roots")}

            You must also set `load-plugins=$module_name` in your Pylint config file.

            While your plugin's code can depend on other first-party code and third-party
            requirements, all first-party dependencies of the plugin must live in the same
            directory or a subdirectory.

            To instead load third-party plugins, add them to a custom resolve alongside
            pylint itself, as described in {doc_url("docs/python/overview/lockfiles#lockfiles-for-tools")}.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to http://pylint.pycqa.org/en/latest/user_guide/run.html#command-line-options for
        # how config files are discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".pylintrc", *(os.path.join(d, "pylintrc") for d in ("", *dirs))],
            check_content={"pyproject.toml": b"[tool.pylint.", "setup.cfg": b"[pylint."},
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


class PylintFirstPartyPlugins(BaseFirstPartyPlugins):
    pass


@rule(desc="Prepare [pylint].source_plugins", level=LogLevel.DEBUG)
async def pylint_first_party_plugins(pylint: Pylint) -> PylintFirstPartyPlugins:
    return await resolve_first_party_plugins(pylint.source_plugins, PylintFirstPartyPlugins)


def rules():
    return (
        *collect_rules(),
        UnionRule(ExportableTool, Pylint),
    )
