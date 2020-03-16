# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

ctypes_compatible_cpp_library(
  name='cpp_library',
  sources=['some_more_math.hpp', 'some_more_math.cpp'],
  ctypes_native_library=native_artifact(lib_name='asdf-cpp_ctypes-with-extra-compiler-flags'),
  compiler_option_sets={'asdf'},
)

python_dist(
  name="ctypes",
  sources=[
    'setup.py',
    'ctypes_python_pkg/__init__.py',
    'ctypes_python_pkg/ctypes_wrapper.py',
  ],
  dependencies=[
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
