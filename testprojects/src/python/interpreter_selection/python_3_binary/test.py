# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from interpreter_selection.python_3_binary.main import main


# A simple example to test a python 3 binary target
# Note that 1/2 = 0 in python 2 and 1/2 = 0.5 in python 3

def test_main():
  print(sys.executable)
  assert main() == 0.5
