# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':hello_directory',
    ':tensorflow_custom_op_directory',
    ':usethriftpy_directory',
  ],
)

files(
  name = 'hello_directory',
  sources = ['hello/**/*'],
)

files(
  name = 'tensorflow_custom_op_directory',
  sources = ['tensorflow_custom_op/**/*'],
  dependencies = [
    'examples/3rdparty:python_directory',
    'examples/src/python/example:tensorflow_custom_op_directory',
  ],
)

files(
  name = 'usethriftpy_directory',
  sources = ['usethriftpy/**/*'],
  dependencies = [
    'examples/3rdparty:python_directory',
    'examples/src/thrift/org/pantsbuild/example:distance_directory',
    'examples/src/thrift/org/pantsbuild/example:precipitation_directory',
  ],
)
