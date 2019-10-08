# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':element_directory',
    ':roots_directory',
    ':temperature_directory',
  ],
)

files(
  name = 'element_directory',
  sources = rglobs('element/*'),
)

files(
  name = 'roots_directory',
  sources = rglobs('roots/*'),
)

files(
  name = 'temperature_directory',
  sources = rglobs('temperature/*'),
)
