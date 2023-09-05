# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.goals import lockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonResolveField,
    PythonTestsBatchCompatibilityTagField,
    PythonTestsExtraEnvVarsField,
    PythonTestSourceField,
    PythonTestsTimeoutField,
    PythonTestsXdistConcurrencyField,
    SkipPythonTestsField,
)
from pants.core.goals.test import RuntimePackageDependenciesField, TestFieldSet
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.rules import collect_rules
from pants.engine.target import Target
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption, StrOption
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class PythonTestFieldSet(TestFieldSet):
    required_fields = (PythonTestSourceField,)

    source: PythonTestSourceField
    interpreter_constraints: InterpreterConstraintsField
    timeout: PythonTestsTimeoutField
    runtime_package_dependencies: RuntimePackageDependenciesField
    extra_env_vars: PythonTestsExtraEnvVarsField
    xdist_concurrency: PythonTestsXdistConcurrencyField
    batch_compatibility_tag: PythonTestsBatchCompatibilityTagField
    resolve: PythonResolveField
    environment: EnvironmentField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPythonTestsField).value


class PyTest(PythonToolBase):
    options_scope = "pytest"
    name = "Pytest"
    help = "The pytest Python test framework (https://docs.pytest.org/)."

    # Pytest 7.1.0 introduced a significant bug that is apparently not fixed as of 7.1.1 (the most
    # recent release at the time of writing). see https://github.com/pantsbuild/pants/issues/14990.
    # TODO: Once this issue is fixed, loosen this to allow the version to float above the bad ones.
    #  E.g., as default_version = "pytest>=7,<8,!=7.1.0,!=7.1.1"
    default_requirements = [
        "pytest==7.0.1",
        "pytest-cov>=2.12,!=2.12.1,<3.1",
        "pytest-xdist>=2.5,<3",
    ]

    default_main = ConsoleScript("pytest")

    default_lockfile_resource = ("pants.backend.python.subsystems", "pytest.lock")

    args = ArgsListOption(example="-k test_foo --quiet", passthrough=True)
    junit_family = StrOption(
        default="xunit2",
        advanced=True,
        help=softwrap(
            """
            The format of generated junit XML files. See
            https://docs.pytest.org/en/latest/reference.html#confval-junit_family.
            """
        ),
    )
    execution_slot_var = StrOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            If a non-empty string, the process execution slot id (an integer) will be exposed
            to tests under this environment variable name.
            """
        ),
    )
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file understood by Pytest
            (https://docs.pytest.org/en/latest/reference/customize.html#configuration-file-formats).
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
            If true, Pants will include all relevant Pytest config files (e.g. `pytest.ini`)
            during runs. See
            https://docs.pytest.org/en/stable/customize.html#finding-the-rootdir for where
            config files should be located for Pytest to discover them.

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )
    xdist_enabled = BoolOption(
        default=False,
        advanced=False,
        help=softwrap(
            """
            If true, Pants will use `pytest-xdist` (https://pytest-xdist.readthedocs.io/en/latest/)
            to parallelize tests within each `python_test` target.

            NOTE: Enabling `pytest-xdist` can cause high-level scoped fixtures (for example `session`)
            to execute more than once. See the `pytest-xdist` docs for more info:
            https://pypi.org/project/pytest-xdist/#making-session-scoped-fixtures-execute-only-once
            """
        ),
    )

    skip = SkipOption("test")

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://docs.pytest.org/en/stable/customize.html#finding-the-rootdir for how
        # config files are discovered.
        check_existence = []
        check_content = {}
        for d in ("", *dirs):
            check_existence.append(os.path.join(d, "pytest.ini"))
            check_content[os.path.join(d, "pyproject.toml")] = b"[tool.pytest.ini_options]"
            check_content[os.path.join(d, "tox.ini")] = b"[pytest]"
            check_content[os.path.join(d, "setup.cfg")] = b"[tool:pytest]"

        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=check_existence,
            check_content=check_content,
        )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
    )
