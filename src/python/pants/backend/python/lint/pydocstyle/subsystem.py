# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.lint.pydocstyle.skip_field import SkipPydocstyleField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonSourceField
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules
from pants.engine.target import FieldSet, Target
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class PydocstyleFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPydocstyleField).value


class Pydocstyle(PythonToolBase):
    options_scope = "pydocstyle"
    name = "Pydocstyle"
    help_short = "A tool for checking compliance with Python docstring conventions (http://www.pydocstyle.org/en/stable/)."

    default_main = ConsoleScript("pydocstyle")
    default_requirements = ["pydocstyle[toml]>=6.1.1,<7.0"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.pydocstyle", "pydocstyle.lock")

    skip = SkipOption("lint")
    args = ArgsListOption(example="--select=D101,D102")
    config = FileOption(
        default=None,
        advanced=True,
        help="Path to a Pydocstyle config file (http://www.pydocstyle.org/en/stable/usage.html#configuration-files).",
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during runs
            (`setup.cfg`, `tox.ini`, `.pydocstyle`, `.pydocstyle.ini`, `.pydocstylerc`, `.pydocstylerc.ini`,
            and `pyproject.toml`) searching for the configuration file in this particular order.

            Please note that even though `pydocstyle` keeps looking for a configuration file up the
            directory tree until one is found, Pants will only search for the config files in the
            repository root (from where you would normally run the `{bin_name()}` command).

            Use `[{cls.options_scope}].config` instead if your config is in a non-standard location.
            """
        ),
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to http://www.pydocstyle.org/en/stable/usage.html#configuration-files. Pydocstyle will search
        # configuration files in a particular order.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"{self.options_scope}.config",
            discovery=self.config_discovery,
            check_existence=[
                ".pydocstyle",
                ".pydocstyle.ini",
                ".pydocstylerc",
                ".pydocstylerc.ini",
            ],
            check_content={
                "setup.cfg": b"[pydocstyle]",
                "tox.ini": b"[pydocstyle]",
                "pyproject.toml": b"[tool.pydocstyle]",
            },
        )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
    )
