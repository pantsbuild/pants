# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

ctypes_compatible_c_library(
  name='c_library',
  sources=['some_math.h', 'some_math.c', 'src-subdir/add_three.h', 'src-subdir/add_three.c'],
  ctypes_native_library=native_artifact(lib_name='asdf-c_ctypes'),
)

ctypes_compatible_cpp_library(
  name='cpp_library',
  sources=['some_more_math.hpp', 'some_more_math.cpp'],
  ctypes_native_library=native_artifact(lib_name='asdf-cpp_ctypes'),
)

python_dist(
  sources=[
    'setup.py',
    'ctypes_python_pkg/__init__.py',
    'ctypes_python_pkg/ctypes_wrapper.py',
  ],
  dependencies=[
    ':c_library',
    ':cpp_library',
  ],
)

python_binary(
  name='bin',
  sources=['main.py'],
  dependencies=[
    ':ctypes',
  ],
  platforms=['current'],
)

python_binary(
  name='with_platforms',
  sources=['main.py'],
  dependencies=[
    ':ctypes',
    'testprojects/3rdparty/python:numpy',
  ],
  platforms=[
    "linux-x86_64",
    "macosx-10.13-x86_64",
  ],
)
