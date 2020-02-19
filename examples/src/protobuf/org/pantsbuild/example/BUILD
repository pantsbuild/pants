# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':distance_directory',
    ':grpcio_directory',
    ':imports_directory',
    ':unpacked_jars_directory',
  ],
)

files(
  name = 'distance_directory',
  sources = ['distance/**/*'],
)

files(
  name = 'grpcio_directory',
  sources = ['grpcio/**/*'],
  dependencies = [
    'examples:3rdparty_directory',
  ],
)

files(
  name = 'imports_directory',
  sources = ['imports/**/*'],
)

files(
  name = 'unpacked_jars_directory',
  sources = ['unpacked_jars/**/*'],
)

