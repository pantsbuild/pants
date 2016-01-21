# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name = 'cache_manager',
  sources = ['test_cache_manager.py'],
  dependencies = [
    'src/python/pants/invalidation',
    'tests/python/pants_test/testutils:mock_logger',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

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
  name = 'versioned_cache',
  sources = ['test_versioned_cache.py'],
  dependencies = [
    'src/python/pants/build_graph:build_graph',
    'src/python/pants/invalidation:invalidation',
    'src/python/pants/task:task',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)
