# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys


# Useful for testing which interpreter the pex machinery selects.

v = sys.version_info
print('%d.%d.%d' % v[0:3])


def say_hello():
  # NOTE: Do not change this text without changing tests that check for it.
  print('echo_interpreter_version loaded successfully.')
