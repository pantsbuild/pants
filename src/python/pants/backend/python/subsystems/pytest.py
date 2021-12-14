# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import Iterable, cast

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    PythonResolveField,
    PythonTestsExtraEnvVarsField,
    PythonTestSourceField,
    PythonTestsTimeoutField,
    SkipPythonTestsField,
    format_invalid_requirement_string_error,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.test import RuntimePackageDependenciesField, TestFieldSet
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    AllTargetsRequest,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.option.custom_types import shell_str
from pants.util.docutil import doc_url, git_url
from pants.util.logging import LogLevel
from pants.util.memo import memoized_method


@dataclass(frozen=True)
class PythonTestFieldSet(TestFieldSet):
    required_fields = (PythonTestSourceField,)

    source: PythonTestSourceField
    timeout: PythonTestsTimeoutField
    runtime_package_dependencies: RuntimePackageDependenciesField
    extra_env_vars: PythonTestsExtraEnvVarsField
    resolve: PythonResolveField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPythonTestsField).value


class PyTest(PythonToolBase):
    options_scope = "pytest"
    help = "The pytest Python test framework (https://docs.pytest.org/)."

    # This should be kept in sync with `requirements.txt`.
    # TODO: To fix this, we should allow using a `target_option` referring to a
    #  `python_requirement` to override the version.
    default_version = "pytest>=6.2.4,<6.3"
    # N.B.: We avoid 2.12.1 since it switched from a `coverage[toml]` dependency introduced in
    # 2.12.0 to a direct dependency on `toml`. This is broken for newer versions of `coverage` where
    # the `toml` extra is mapped to `tomli`. This direct `toml` dependency was reverted in favor of
    # `coverage[toml]` in 3.0.0.
    default_extra_requirements = ["pytest-cov>=2.12,!=2.12.1,<3.1"]

    default_main = ConsoleScript("pytest")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "pytest_lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/pytest_lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help='Arguments to pass directly to Pytest, e.g. `--pytest-args="-k test_foo --quiet"`',
        )
        register(
            "--timeouts",
            type=bool,
            default=True,
            help="Enable test target timeouts. If timeouts are enabled then test targets with a "
            "timeout= parameter set on their target will time out after the given number of "
            "seconds if not completed. If no timeout is set, then either the default timeout "
            "is used or no timeout is configured.",
        )
        register(
            "--timeout-default",
            type=int,
            advanced=True,
            help=(
                "The default timeout (in seconds) for a test target if the `timeout` field is not "
                "set on the target."
            ),
        )
        register(
            "--timeout-maximum",
            type=int,
            advanced=True,
            help="The maximum timeout (in seconds) that may be used on a `python_tests` target.",
        )
        register(
            "--junit-family",
            type=str,
            default="xunit2",
            advanced=True,
            help=(
                "The format of generated junit XML files. See "
                "https://docs.pytest.org/en/latest/reference.html#confval-junit_family."
            ),
        )
        register(
            "--execution-slot-var",
            type=str,
            default=None,
            advanced=True,
            help=(
                "If a non-empty string, the process execution slot id (an integer) will be exposed "
                "to tests under this environment variable name."
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include all relevant Pytest config files (e.g. `pytest.ini`) "
                "during runs. See "
                "https://docs.pytest.org/en/stable/customize.html#finding-the-rootdir for where "
                "config files should be located for Pytest to discover them."
            ),
        )

    @property
    def all_requirements(self) -> tuple[str, ...]:
        return (self.version, *self.extra_requirements)

    @property
    def timeouts_enabled(self) -> bool:
        return cast(bool, self.options.timeouts)

    @property
    def timeout_default(self) -> int | None:
        return cast("int | None", self.options.timeout_default)

    @property
    def timeout_maximum(self) -> int | None:
        return cast("int | None", self.options.timeout_maximum)

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
            discovery=cast(bool, self.options.config_discovery),
            check_existence=check_existence,
            check_content=check_content,
        )

    @memoized_method
    def validate_pytest_cov_included(self) -> None:
        for s in self.extra_requirements:
            try:
                req = PipRequirement.parse(s).project_name
            except Exception as e:
                raise ValueError(
                    format_invalid_requirement_string_error(
                        s, e, description_of_origin="`[pytest].extra_requirements`"
                    )
                )
            if canonicalize_project_name(req) == "pytest-cov":
                return

        raise ValueError(
            "You set `[test].use_coverage`, but `[pytest].extra_requirements` is missing "
            "`pytest-cov`, which is needed to collect coverage data.\n\nThis happens when "
            "overriding the `extra_requirements` option. Please either explicitly add back "
            "`pytest-cov` or use `extra_requirements.add` to keep Pants's default, rather than "
            "overriding it. Run `./pants help-advanced pytest` to see the default version of "
            f"`pytest-cov` and see {doc_url('options#list-values')} for more on adding vs. "
            "overriding list options."
        )


class PytestLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = PyTest.options_scope


@rule(
    desc=(
        "Determine all Python interpreter versions used by Pytest in your project (for "
        "lockfile usage)"
    ),
    level=LogLevel.DEBUG,
)
async def setup_pytest_lockfile(
    _: PytestLockfileSentinel, pytest: PyTest, python_setup: PythonSetup
) -> PythonLockfileRequest:
    if not pytest.uses_lockfile:
        return PythonLockfileRequest.from_tool(pytest)

    # Even though we run each python_tests target in isolation, we need a single lockfile that
    # works with them all (and their transitive deps).
    #
    # This first computes the constraints for each individual `python_test` target
    # (which will AND across each target in the closure). Then, it ORs all unique resulting
    # interpreter constraints. The net effect is that every possible Python interpreter used will
    # be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    transitive_targets_per_test = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest([tgt.address]))
        for tgt in all_tgts
        if PythonTestFieldSet.is_applicable(tgt)
    )
    unique_constraints = {
        InterpreterConstraints.create_from_targets(transitive_targets.closure, python_setup)
        for transitive_targets in transitive_targets_per_test
    }
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return PythonLockfileRequest.from_tool(
        pytest, constraints or InterpreterConstraints(python_setup.interpreter_constraints)
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, PytestLockfileSentinel))
