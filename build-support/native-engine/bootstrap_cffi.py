# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from pants.engine.subsystem.native import bootstrap_c_source


if __name__ == '__main__':
  try:
    output_dir = sys.argv[1]
  except Exception:
    print('usage: {} <output dir>'.format(sys.argv[0]))

  bootstrap_c_source(output_dir)
