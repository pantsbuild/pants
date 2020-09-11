# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'build_invalidator',
  sources = ['test_build_invalidator.py'],
  dependencies = [
    'src/python/pants/invalidation',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'cache_manager',
  sources = ['test_cache_manager.py'],
  dependencies = [
    'src/python/pants/invalidation',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'strict_deps_invalidation_integration',
  sources = ['test_strict_deps_invalidation_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/testutil:int-test',
    'testprojects/tests/java/org/pantsbuild/testproject:strictdeps_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 700,
)
