# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

from interpreter_selection.python_3_selection_testing.lib_py3 import say_something


# A simple example to test building/running/testing a python 3 binary target


def main():
  v = sys.version_info
  print(sys.executable)
  print('%d.%d.%d' % v[0:3])
  return say_something()

if __name__ == '__main__':
  main()
