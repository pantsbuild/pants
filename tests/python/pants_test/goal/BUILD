# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='artifact_cache_stats',
  sources= ['test_artifact_cache_stats.py'],
  dependencies = [
    '3rdparty/python:requests',
    'src/python/pants/cache',
    'src/python/pants/goal:artifact_cache_stats',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='other',
  sources=[
    'test_context.py',
    'test_products.py',
    'test_run_tracker.py',
    'test_union_products.py',
  ],
  dependencies = [
    '3rdparty/python:twitter.common.collections',
    'src/python/pants/build_graph',
    'src/python/pants/goal:products',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='run_tracker_integration',
  sources=[
    'test_run_tracker_integration.py'
  ],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)