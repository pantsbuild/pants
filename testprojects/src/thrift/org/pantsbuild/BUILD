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
  sources=rglobs('constants_only/*'),
)

files(
  name='testproject_directory',
  sources=rglobs('testproject/*'),
)

files(
  name='thrift_exports_directory',
  sources=rglobs('thrift_exports/*'),
)
