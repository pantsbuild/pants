# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from ctypes_python_pkg.ctypes_wrapper import get_node_name


if __name__ == '__main__':
  print('node_name={}'.format(get_node_name()))
