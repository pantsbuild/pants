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
    ':cache_server',
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

python_tests(
  name = 'caching',
  sources = ['test_caching.py'],
  dependencies = [
    'src/python/pants/task:task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:payload',
    'src/python/pants/build_graph:build_graph',
    'src/python/pants/cache:cache',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'caching_dereference_symlinks',
  sources = ['test_caching_tarball_deference.py'],
  dependencies = [
    'src/python/pants/task:task',
    'src/python/pants/cache:cache',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_library(
  name = 'cache_server',
  sources = ['cache_server.py'],
  dependencies = [
    '3rdparty/python:six',
    'tests/python/pants_test/testutils:file_test_util',
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
  ],
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

python_tests(
  name = 'cache_cleanup_integration',
  sources = ['test_cache_cleanup_integration.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:zinc',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout=90,
)
