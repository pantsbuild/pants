# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':constants_only_directory',
    ':testproject_directory',
    ':thrift_exports_directory',
  ],
)

files(
  name='constants_only_directory',
  sources=['constants_only/**/*'],
  dependencies = [
    'examples/3rdparty:python_directory',
  ],
)

files(
  name='testproject_directory',
  sources=['testproject/**/*'],
  dependencies = [
    'examples/3rdparty:python_directory',
  ],
)

files(
  name='thrift_exports_directory',
  sources=['thrift_exports/**/*'],
  dependencies = [
    'examples/3rdparty:python_directory',
  ],
)
