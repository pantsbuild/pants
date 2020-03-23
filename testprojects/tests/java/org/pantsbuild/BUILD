# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':build_parsing_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:all_directories',
  ],
)

files(
  name = 'build_parsing_directory',
  sources = ['build_parsing/**/*'],
)
