# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time

from pants.base.exiter import Exiter
from pants.bin.pants_runner import PantsRunner
from pants.util.contextutil import maybe_profiled


TEST_STR = 'T E S T'


def test():
  """An alternate testing entrypoint that helps avoid dependency linkages
  into `tests/python` from the `bin` target."""
  print(TEST_STR)


def test_env():
  """An alternate test entrypoint for exercising scrubbing."""
  import os
  print('PANTS_ENTRYPOINT={}'.format(os.environ.get('PANTS_ENTRYPOINT')))


def main():
  start_time = time.time()

  exiter = Exiter()
  exiter.set_except_hook()

  with maybe_profiled(os.environ.get('PANTSC_PROFILE')):
    try:
      PantsRunner(exiter, start_time=start_time).run()
    except KeyboardInterrupt:
      exiter.exit_and_fail(b'Interrupted by user.')
