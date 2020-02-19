# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':hello_directory',
    ':specs2_directory',
  ],
)

files(
  name = 'hello_directory',
  sources = ['hello/**/*'],
  dependencies = [
    'examples/src/scala/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'specs2_directory',
  sources = ['specs2/**/*'],
)
