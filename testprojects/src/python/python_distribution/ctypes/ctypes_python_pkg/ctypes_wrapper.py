# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ctypes
import os


def get_generated_shared_lib(lib_name):
  filename = 'lib{}.so'.format(lib_name)
  rel_path = os.path.join(os.path.dirname(__file__), '..', filename)
  return os.path.normpath(rel_path)


asdf_c_lib_path = get_generated_shared_lib('asdf-c')
asdf_cpp_lib_path = get_generated_shared_lib('asdf-cpp')

asdf_c_lib = ctypes.CDLL(asdf_c_lib_path)
asdf_cpp_lib = ctypes.CDLL(asdf_cpp_lib_path)

def f(x):
  added = asdf_c_lib.add_three(x)
  multiplied = asdf_cpp_lib.multiply_by_three(added)
  return multiplied
