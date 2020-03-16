# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':distance_directory',
    ':precipitation_directory',
  ],
)

page(
  name='readme',
  sources=['README.md'],
  links=[
    'examples/src/java/org/pantsbuild/example:publish',
  ])

files(
  name = 'distance_directory',
  sources = ['distance/**/*'],
  dependencies = [
    'examples/3rdparty:python_directory',
  ],
)

files(
  name = 'precipitation_directory',
  sources = ['precipitation/**/*'],
  dependencies = [
    ':distance_directory',
    'examples/3rdparty:python_directory',
  ],
)
