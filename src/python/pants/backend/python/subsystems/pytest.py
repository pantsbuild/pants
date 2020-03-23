# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, Tuple, cast

from pants.option.custom_types import shell_str
from pants.subsystem.subsystem import Subsystem


class PyTest(Subsystem):
    options_scope = "pytest"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            fingerprint=True,
            help='Arguments to pass directly to Pytest, e.g. `--pytest-args="-k test_foo --quiet"`',
        )
        register(
            "--version",
            default="pytest>=5.3.5,<5.4",
            fingerprint=True,
            help="Requirement string for Pytest.",
        )
        register(
            "--pytest-plugins",
            type=list,
            fingerprint=True,
            default=[
                "pytest-timeout>=1.3.4,<1.4",
                "pytest-cov>=2.8.1,<2.9",
                # NB: zipp has frequently destabilized builds due to floating transitive versions under pytest.
                "zipp==2.1.0",
            ],
            help="Requirement strings for any plugins or additional requirements you'd like to use.",
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
            help="The default timeout (in seconds) for a test target if the timeout field is not set on the target.",
        )
        register(
            "--timeout-maximum",
            type=int,
            advanced=True,
            help="The maximum timeout (in seconds) that can be set on a test target.",
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
