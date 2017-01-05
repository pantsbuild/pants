# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'build_invalidator',
  sources = ['test_build_invalidator.py'],
  dependencies = [
    'src/python/pants/invalidation',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'cache_manager',
  sources = ['test_cache_manager.py'],
  dependencies = [
    'src/python/pants/invalidation',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/testutils:mock_logger',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'strict_deps_invalidation_integration',
  sources = ['test_strict_deps_invalidation_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout = 120,
)
