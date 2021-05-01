# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable, cast

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.custom_types import file_option, shell_str
from pants.option.subsystem import Subsystem


class PyTest(Subsystem):
    options_scope = "pytest"
    help = "The pytest Python test framework (https://docs.pytest.org/)."

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
            "--version",
            # This should be kept in sync with `requirements.txt`.
            # TODO: To fix this, we should allow using a `target_option` referring to a
            #  `python_requirement_library` to override the version.
            default="pytest>=6.0.1,<6.3",
            advanced=True,
            help="Requirement string for Pytest.",
        )
        register(
            "--pytest-plugins",
            type=list,
            advanced=True,
            # TODO: When updating pytest-cov to 2.12+, update the help message for
            #  `[coverage-py].config` to not mention installing TOML.
            default=["pytest-cov>=2.10.1,<2.12"],
            help=(
                "Requirement strings for any plugins or additional requirements you'd like to use."
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
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help="Path to pytest.ini or alternative Pytest config file.",
            removal_version="2.6.0.dev0",
            removal_hint=(
                "Pants now auto-discovers config files, so there is no need to set "
                "`[pytest].config` if `[pytest].config_discovery` is enabled (the default)."
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

    def get_requirement_strings(self) -> tuple[str, ...]:
        """Returns a tuple of requirements-style strings for Pytest and Pytest plugins."""
        return (self.options.version, *self.options.pytest_plugins)

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
            specified=cast("str | None", self.options.config),
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=check_existence,
            check_content=check_content,
        )
