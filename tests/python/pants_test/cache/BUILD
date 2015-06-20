# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'cache',
  sources = globs('*.py'),
  dependencies = [
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/base:build_invalidator',
    'src/python/pants/cache',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/testutils',
  ]
)
