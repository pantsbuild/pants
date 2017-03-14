# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import locale
import warnings


# We want to present warnings to the user, set this up before importing any of our own code,
# to ensure all deprecation warnings are seen, including module deprecations.
# The "default" action displays a warning for a particular file and line number exactly once.
# See https://docs.python.org/2/library/warnings.html#the-warnings-filter for the complete list.
warnings.simplefilter('default', DeprecationWarning)

from pants.bin.pants_runner import PantsRunner  # isort:skip
from pants.bin.exiter import Exiter  # isort:skip


class InvalidLocaleError(Exception):
  """Raised when a valid locale can't be found."""

# Sanity check for locale, See https://github.com/pantsbuild/pants/issues/2465.
# This check is done early to give good feedback to user on how to fix the problem. Other
# libraries called by Pants may fail with more obscure errors.
try:
  locale.getlocale()[1] or locale.getdefaultlocale()[1]
except Exception as e:
  raise InvalidLocaleError(
      "{}: {}\n"
      "  Could not get a valid locale. Check LC_* and LANG environment settings.\n"
      "  Example for US English:\n"
      "    LC_ALL=en_US.UTF-8\n"
      "    LANG=en_US.UTF-8".format(type(e).__name__, e))


def main():
  exiter = Exiter()
  exiter.set_except_hook()

  try:
    PantsRunner(exiter).run()
  except KeyboardInterrupt:
    exiter.exit_and_fail(b'Interrupted by user.')


if __name__ == '__main__':
  main()
