# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from typing import Iterable, cast

from pants.backend.experimental.python.lockfile import (
    PythonLockfileRequest,
    PythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonTestsSources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.base.deprecated import resolve_conflicting_options
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest, UnexpandedTargets
from pants.engine.unions import UnionRule
from pants.option.custom_types import shell_str
from pants.python.python_setup import PythonSetup
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


class PyTest(PythonToolBase):
    options_scope = "pytest"
    help = "The pytest Python test framework (https://docs.pytest.org/)."

    # This should be kept in sync with `requirements.txt`.
    # TODO: To fix this, we should allow using a `target_option` referring to a
    #  `python_requirement_library` to override the version.
    default_version = "pytest>=6.0.1,<6.3"
    # TODO: When updating pytest-cov to 2.12+, update the help message for
    #  `[coverage-py].config` to not mention installing TOML.
    default_extra_requirements = ["pytest-cov>=2.10.1,<2.12"]

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
            "--pytest-plugins",
            type=list,
            advanced=True,
            default=PyTest.default_extra_requirements,
            help=(
                "Requirement strings for any plugins or additional requirements you'd like to use."
            ),
            removal_version="2.8.0.dev0",
            removal_hint=(
                "Use `[pytest].extra_requirements` instead, which behaves the same. (The option is "
                "being renamed for uniformity with other Python tools.)"
            ),
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
            "--junit-xml-dir",
            type=str,
            metavar="<DIR>",
            default=None,
            advanced=True,
            help="Specifying a directory causes Junit XML result files to be emitted under "
            "that dir for each test run.",
        )
        register(
            "--junit-family",
            type=str,
            default="xunit2",
            advanced=True,
            help=(
                "The format of the generated XML file. See "
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
        extras = resolve_conflicting_options(
            old_option="pytest_plugins",
            new_option="extra_requirements",
            old_scope=self.options_scope,
            new_scope=self.options_scope,
            old_container=self.options,
            new_container=self.options,
        )
        return (self.version, *extras)

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


class PytestLockfileSentinel(PythonToolLockfileSentinel):
    pass


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
    # Even though we run each python_tests target in isolation, we need a single lockfile that
    # works with them all (and their transitive deps).
    #
    # This first computes the constraints for each individual `python_tests` target
    # (which will AND across each target in the closure). Then, it ORs all unique resulting
    # interpreter constraints. When paired with
    # `InterpreterConstraints.partition_by_major_minor_versions`, the net effect is that
    # every possible Python interpreter used will be covered.
    all_build_targets = await Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")]))
    transitive_targets_per_test = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest([tgt.address]))
        for tgt in all_build_targets
        if tgt.has_field(PythonTestsSources)
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
