# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'artifact',
  sources = ['test_artifact.py'],
  dependencies = [
    'src/python/pants/cache',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'artifact_cache',
  sources = ['test_artifact_cache.py'],
  dependencies = [
    'src/python/pants/cache',
    'src/python/pants/invalidation',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)

python_tests(
  name = 'cache_setup',
  sources = ['test_cache_setup.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/cache',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/task',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/testutils:mock_logger',
  ]
)

python_library(
  name = 'delay_server',
  sources = ['delay_server.py'],
  dependencies = [
  '3rdparty/python:six',
  ]
)

python_tests(
  name = 'pinger',
  sources = ['test_pinger.py'],
  dependencies = [
    'src/python/pants/cache',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/cache:delay_server',
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
