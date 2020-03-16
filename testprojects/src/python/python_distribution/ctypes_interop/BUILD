# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_dist(
  sources=[
    'setup.py',
    'ctypes_python_pkg/__init__.py',
    'ctypes_python_pkg/ctypes_wrapper.py',
  ],
  dependencies=[
    'testprojects/src/python/python_distribution/ctypes_interop/some-more-math',
    'testprojects/src/python/python_distribution/ctypes_interop/wrapped-math',
  ],
)

python_binary(
  name='bin',
  sources=['main.py'],
  dependencies=[
    ':ctypes_interop',
  ],
  platforms=['current'],
)
