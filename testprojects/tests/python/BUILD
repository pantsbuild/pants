# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    'testprojects/tests/python/pants:all_directories',
  ],
)

files(
  name = 'owners_integration_target',
  sources = ['pants/BUILD'],
  dependencies = [
    'testprojects/tests/python/pants:dummies_directory',
  ],
)
