# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

ctypes_compatible_c_library(
  name='c_library',
  sources=['some_math.h', 'some_math.c', 'src-subdir/add_three.h', 'src-subdir/add_three.c'],
  ctypes_native_library=native_artifact(lib_name='asdf-c'),
)

ctypes_compatible_cpp_library(
  name='cpp_library',
  sources=['some_more_math.hpp', 'some_more_math.cpp'],
  ctypes_native_library=native_artifact(lib_name='asdf-cpp'),
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
  source='main.py',
  dependencies=[
    ':ctypes',
  ],
  platforms=['current'],
)
