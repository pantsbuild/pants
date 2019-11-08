# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':cp-directories_directory',
    ':exports_directory',
    ':non_exports_directory',
  ],
)


files(
  name='cp-directories_directory',
  sources=rglobs('cp-directories/*'),
)

files(
  name='exports_directory',
  sources=rglobs('exports/*'),
)

files(
  name='non_exports_directory',
  sources=rglobs('non_exports/*'),
)
