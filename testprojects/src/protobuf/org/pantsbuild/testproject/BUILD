# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':distance_directory',
    ':import_from_buildroot_directory',
    ':proto-ordering_directory',
    ':utf8proto_directory',
  ],
)

files(
  name = 'distance_directory',
  sources = ['distance/**/*'],
)

files(
  name = 'import_from_buildroot_directory',
  sources = ['import_from_buildroot/**/*'],
)

files(
  name = 'proto-ordering_directory',
  sources = ['proto-ordering/**/*'],
)

files(
  name = 'utf8proto_directory',
  sources = ['utf8proto/**/*'],
)
