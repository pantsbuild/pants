# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':hello_directory',
    ':useproto_directory',
    ':useprotoimports_directory',
    ':usethrift_directory',
  ],
)

files(
  name = 'hello_directory',
  sources = ['hello/**/*'],
  dependencies = [
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'useproto_directory',
  sources = ['useproto/**/*'],
  dependencies = [
    'examples/src/protobuf/org/pantsbuild/example:distance_directory',
  ],
)

files(
  name = 'useprotoimports_directory',
  sources = ['useprotoimports/**/*'],
  dependencies = [
    'examples/src/protobuf/org/pantsbuild/example:imports_directory',
  ],
)

files(
  name = 'usethrift_directory',
  sources = ['usethrift/**/*'],
  dependencies = [
    'examples/src/thrift/org/pantsbuild/example:distance_directory',
    'examples/src/thrift/org/pantsbuild/example:precipitation_directory',
  ],
)
