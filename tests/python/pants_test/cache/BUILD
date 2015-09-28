# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'cache',
  dependencies = [
    ':artifact_cache',
    ':cache_setup',
    ':resolver',
  ]
)

python_tests(
  name = 'artifact_cache',
  sources = globs('*.py'),
  dependencies = [
    'src/python/pants/base:build_invalidator',
    'src/python/pants/cache',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'cache_setup',
  sources = globs('*.py'),
  dependencies = [
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/cache',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/testutils',
  ]
)

python_tests(
  name = 'resolver',
  sources = ['test_resolver.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/cache',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)
