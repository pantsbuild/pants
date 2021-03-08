# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, Tuple, cast

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
            help="The format of the generated XML file. See https://docs.pytest.org/en/latest/reference.html#confval-junit_family.",
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
            help=(
                "Path to pytest.ini or alternative Pytest config file.\n\n"
                "Pytest will attempt to auto-discover the config file,"
                "meaning that it should typically be an ancestor of your"
                "tests, such as in the build root.\n\nPants will not automatically"
                " set --rootdir for you to force Pytest to pick up your config "
                "file, but you can manually set --rootdir in [pytest].args.\n\n"
                "Refer to https://docs.pytest.org/en/stable/customize.html#"
                "initialization-determining-rootdir-and-configfile."
            ),
        )

    def get_requirement_strings(self) -> Tuple[str, ...]:
        """Returns a tuple of requirements-style strings for Pytest and Pytest plugins."""
        return (self.options.version, *self.options.pytest_plugins)

    @property
    def timeouts_enabled(self) -> bool:
        return cast(bool, self.options.timeouts)

    @property
    def timeout_default(self) -> Optional[int]:
        return cast(Optional[int], self.options.timeout_default)

    @property
    def timeout_maximum(self) -> Optional[int]:
        return cast(Optional[int], self.options.timeout_maximum)

    @property
    def config(self) -> Optional[str]:
        return cast(Optional[str], self.options.config)
