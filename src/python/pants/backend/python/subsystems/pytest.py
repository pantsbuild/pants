# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple, cast

from pants.base.deprecated import deprecated_conditional
from pants.option.option_util import flatten_shlexed_list
from pants.subsystem.subsystem import Subsystem


class PyTest(Subsystem):
  options_scope = 'pytest'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--args', type=list, member_type=str, fingerprint=True,
      help="Arguments to pass directly to Pytest, e.g. `--pytest-args=\"-k test_foo --quiet\"`",
    )
    register(
      '--version', default='pytest>=4.6.6,<4.7', fingerprint=True,
      help="Requirement string for Pytest.",
    )
    register(
      '--pytest-plugins',
      type=list,
      fingerprint=True,
      default=[
        'pytest-timeout>=1.3.3,<1.4',
        'pytest-cov>=2.8.1,<3',
        "unittest2>=1.1.0 ; python_version<'3'",
        "more-itertools<6.0.0 ; python_version<'3'",
      ],
      help="Requirement strings for any plugins or additional requirements you'd like to use.",
    )
    register(
      '--timeouts',
      type=bool,
      default=True,
      help='Enable test target timeouts. If timeouts are enabled then test targets with a '
          'timeout= parameter set on their target will time out after the given number of '
          'seconds if not completed. If no timeout is set, then either the default timeout '
          'is used or no timeout is configured.',
    )
    register(
      '--timeout-default',
      type=int,
      advanced=True,
      help='The default timeout (in seconds) for a test target if the timeout field is not set on the target.',
    )
    register(
      '--timeout-maximum',
      type=int,
      advanced=True,
      help='The maximum timeout (in seconds) that can be set on a test target.',
    )

  def get_requirement_strings(self) -> Tuple[str, ...]:
    """Returns a tuple of requirements-style strings for Pytest and Pytest plugins."""
    opts = self.get_options()

    deprecated_conditional(
      lambda: cast(bool, opts.is_default("version")),
      removal_version="1.25.0.dev2",
      entity_description="Pants defaulting to a Python 2-compatible Pytest version",
      hint_message="Pants will soon start defaulting to Pytest 5.x, which no longer supports "
                   "running tests with Python 2. In preparation for this change, you should "
                   "explicitly set what version of Pytest to use in your `pants.ini` under the "
                   "section `pytest`.\n\nIf you need to keep running tests with Python 2, set "
                   "`version` to `pytest>=4.6.6,<4.7` (the current default). If you don't have any "
                   "tests with Python 2 and want the newest Pytest, set `version` to "
                   "`pytest>=5.2.4`."
    )

    return (opts.version, *opts.pytest_plugins)

  def get_args(self) -> Tuple[str, ...]:
    return flatten_shlexed_list(self.get_options().args)
