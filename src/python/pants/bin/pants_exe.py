# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import warnings


# We want to present warnings to the user, set this up before importing any of our own code,
# to ensure all deprecation warnings are seen, including module deprecations.
# The "default" action displays a warning for a particular file and line number exactly once.
# See https://docs.python.org/2/library/warnings.html#the-warnings-filter for the complete list.
warnings.simplefilter('default', DeprecationWarning)

from pants.bin.pants_runner import LocalPantsRunner           # isort:skip
from pants.bin.exiter import Exiter                           # isort:skip


def main():
  exiter = Exiter()
  exiter.set_except_hook()

  try:
    LocalPantsRunner(exiter).run()
  except KeyboardInterrupt:
    exiter.exit_and_fail('Interrupted by user.')


if __name__ == '__main__':
  main()
