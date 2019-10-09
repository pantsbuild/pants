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
  source='README.md',
  links=[
    'examples/src/java/org/pantsbuild/example:publish',
  ])

files(
  name = 'distance_directory',
  sources = rglobs('distance/*'),
)

files(
  name = 'precipitation_directory',
  sources = rglobs('precipitation/*'),
  dependencies = [
    ':distance_directory',
  ],
)
