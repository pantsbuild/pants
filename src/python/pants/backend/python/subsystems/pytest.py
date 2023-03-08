# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
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
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.test import RuntimePackageDependenciesField, TestFieldSet
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption, StrOption
from pants.util.docutil import bin_name, doc_url, git_url
from pants.util.logging import LogLevel
from pants.util.memo import memoized_method
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

    # This should be compatible with requirements.txt, although it can be more precise.
    # TODO: To fix this, we should allow using a `target_option` referring to a
    #  `python_requirement` to override the version.
    # Pytest 7.1.0 introduced a significant bug that is apparently not fixed as of 7.1.1 (the most
    # recent release at the time of writing). see https://github.com/pantsbuild/pants/issues/14990.
    # TODO: Once this issue is fixed, loosen this to allow the version to float above the bad ones.
    #  E.g., as default_version = "pytest>=7,<8,!=7.1.0,!=7.1.1"
    default_version = "pytest==7.0.1"
    default_extra_requirements = ["pytest-cov>=2.12,!=2.12.1,<3.1", "pytest-xdist>=2.5,<3"]
    default_requirements = [default_version, *default_extra_requirements]

    default_main = ConsoleScript("pytest")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "pytest.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/pytest.lock"
    default_lockfile_url = git_url(default_lockfile_path)

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

    export = ExportToolOption()

    skip = SkipOption("test")

    @property
    def all_requirements(self) -> tuple[str, ...]:
        return (self.version, *self.extra_requirements)

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

    @memoized_method
    def validate_pytest_cov_included(self) -> None:
        for s in self.extra_requirements:
            try:
                req = PipRequirement.parse(s).project_name
            except Exception as e:
                raise ValueError(f"Invalid requirement '{s}' in `[pytest].extra_requirements`: {e}")
            if canonicalize_project_name(req) == "pytest-cov":
                return

        raise ValueError(
            softwrap(
                f"""
                You set `[test].use_coverage`, but `[pytest].extra_requirements` is missing
                `pytest-cov`, which is needed to collect coverage data.

                This happens when overriding the `extra_requirements` option. Please either explicitly
                add back `pytest-cov` or use `extra_requirements.add` to keep Pants's default, rather than
                overriding it. Run `{bin_name()} help-advanced pytest` to see the default version of
                `pytest-cov` and see {doc_url('options#list-values')} for more on adding vs.
                overriding list options.
                """
            )
        )


class PytestLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = PyTest.options_scope


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by Pytest in your project
        (for lockfile generation)
        """
    ),
    level=LogLevel.DEBUG,
)
async def setup_pytest_lockfile(
    _: PytestLockfileSentinel, pytest: PyTest, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    if not pytest.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(pytest)

    constraints = await _find_all_unique_interpreter_constraints(python_setup, PythonTestFieldSet)
    return GeneratePythonLockfile.from_tool(pytest, constraints)


class PytestExportSentinel(ExportPythonToolSentinel):
    pass


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by Pytest in your project
        (for `export` goal)
        """
    ),
    level=LogLevel.DEBUG,
)
async def pytest_export(
    _: PytestExportSentinel, pytest: PyTest, python_setup: PythonSetup
) -> ExportPythonTool:
    if not pytest.export:
        return ExportPythonTool(resolve_name=pytest.options_scope, pex_request=None)
    constraints = await _find_all_unique_interpreter_constraints(python_setup, PythonTestFieldSet)
    return ExportPythonTool(
        resolve_name=pytest.options_scope,
        pex_request=pytest.to_pex_request(interpreter_constraints=constraints),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, PytestLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, PytestExportSentinel),
    )
