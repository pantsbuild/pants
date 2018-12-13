# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from ctypes_python_pkg.ctypes_wrapper import f


if __name__ == '__main__':
  x = 3
  print('x={}, f(x)={}'.format(x, f(x)))
