# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO(#7059): add a page() for the README once it is easier to extend the docsite!

# See https://www.tensorflow.org/guide/extend/op!

python_library(
  sources=['zero_out_custom_op.py'],
  dependencies=[
    'examples/3rdparty/python:tensorflow',
    ':tensorflow-zero-out-op-wrapper',
  ],
)

# TODO: allow merging of this and a python_library() somehow! If we could make dependencies (such as
# tensorflow) into install_requires() with the SetupPy task somehow, this would be easy!
python_dist(
  name='tensorflow-zero-out-op-wrapper',
  sources=[
    'setup.py',
    '__init__.py',
    # TODO: we shouldn't have to introduce this second-level package, but I can't figure out how to
    # use wrap_zero_out_op.py at the top level!
    'wrap_lib/wrap_zero_out_op.py',
    'wrap_lib/__init__.py',
  ],
  dependencies=[
    ':tensorflow-zero-out-op',
  ],
)

ctypes_compatible_cpp_library(
  name='tensorflow-zero-out-op',
  dependencies=[
    'examples/3rdparty/python:tensorflow-framework',
  ],
  ctypes_native_library=native_artifact(lib_name='tensorflow-zero-out-operator'),
)


python_binary(
  name='show-tf-version',
  sources=['show_tf_version.py'],
  dependencies=[
    'examples/3rdparty/python:tensorflow',
  ],
  compatibility=['CPython>=3.6,<4'],
)

files(
  name='show-tf-version-files',
  sources=['**/*'],
  dependencies=[
    'examples/3rdparty/python:examples_python_3rdparty',
  ],
)
