# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

from interpreter_selection.python_3_selection_testing.main_py3 import main


def test_main():
  print(sys.executable)
  # Note that ascii exists as a built-in in Python 3 and
  # does not exist in Python 2
  ret = main()
  assert ret == ascii
