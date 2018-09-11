# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ctypes
import os


def get_generated_shared_lib(lib_name):
  # These are the same filenames as in setup.py.
  filename = 'lib{}.so'.format(lib_name)
  # The data files are in the root directory, but we are in ctypes_python_pkg/.
  rel_path = os.path.join(os.path.dirname(__file__), '..', filename)
  return os.path.normpath(rel_path)


asdf_cpp_lib_path = get_generated_shared_lib('asdf-cpp-tp')
asdf_cpp_lib = ctypes.CDLL(asdf_cpp_lib_path)

libc = ctypes.CDLL(ctypes.util.find_library('c'))
libc.free.argtypes = (ctypes.c_void_p,)

def f(x):
  added = x + 3
  multiplied = asdf_cpp_lib.multiply_by_three(added)
  return multiplied

asdf_cpp_lib.get_node_name_xml.argtypes = (ctypes.c_char_p,)
asdf_cpp_lib.get_node_name_xml.restype = ctypes.c_char_p

test_xml_path = os.path.join(os.path.dirname(__file__), '..', 'test.xml')

def get_node_name():
  return asdf_cpp_lib.get_node_name_xml(test_xml_path)
