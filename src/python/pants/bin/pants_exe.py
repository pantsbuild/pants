# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.bin.pants_runner import PantsRunner
from pants.bin.exiter import Exiter


def main():
  exiter = Exiter()
  exiter.set_except_hook()

  try:
    PantsRunner(exiter).run()
  except KeyboardInterrupt:
    exiter.exit_and_fail(b'Interrupted by user.')
