# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

## Third party integration testing.

ctypes_compatible_c_library(
  name='a_c_library',
  sources=['src-subdir/add_three.h', 'src-subdir/add_three.c'],
  ctypes_native_library=native_artifact(lib_name='asdf-c-tp'),
  fatal_warnings=False
)

ctypes_compatible_cpp_library(
  name='cpp_library_with_third_party',
  sources=['some_more_math.hpp', 'some_more_math_with_third_party.cpp'],
  ctypes_native_library=native_artifact(lib_name='asdf-cpp-tp'),
  dependencies=[':rang', ':cereal'],
  fatal_warnings=False
)

python_dist(
  name='python_dist_with_third_party_cpp',
  sources=[
    'setup.py',
    'ctypes_python_pkg/__init__.py',
    'ctypes_python_pkg/ctypes_wrapper.py',
  ],
  dependencies=[
    ':a_c_library',
    ':cpp_library_with_third_party',
  ],
)

python_binary(
  name='bin_with_third_party',
  source='main.py',
  dependencies=[
    ':python_dist_with_third_party_cpp',
  ],
)

external_native_library(
  name='rang',
  packages=[
     'rang/3.1.0@rang/stable',
  ],
)

external_native_library(
  name='cereal',
  packages=[
     'cereal/1.2.2@conan/stable',
  ],
)
