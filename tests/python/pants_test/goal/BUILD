# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='artifact_cache_stats',
  sources= ['test_artifact_cache_stats.py'],
  dependencies=[
    'src/python/pants/cache',
    'src/python/pants/goal:artifact_cache_stats',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='other',
  sources=[
    'test_context.py',
    'test_products.py',
    'test_run_tracker.py',
    'test_union_products.py',
  ],
  dependencies=[
    'src/python/pants/auth',
    'src/python/pants/build_graph',
    'src/python/pants/goal:products',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:ordered_set',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='run_tracker_integration',
  sources=[
    'test_run_tracker_integration.py'
  ],
  dependencies=[
    'src/python/pants/goal:run_tracker',
    'src/python/pants/testutil:int-test',
    'tests/python/pants_test/goal/data:plugin',
    'testprojects/src/java/org/pantsbuild/testproject:extra_jvm_options_directory',
    'testprojects/src/java/org/pantsbuild/testproject:unicode_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 900,
)
