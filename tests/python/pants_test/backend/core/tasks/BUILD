# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'cache_cleanup_integration',
  sources = ['test_cache_cleanup_integration.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:zinc',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
    'src/python/pants/util:contextutil',
  ],
  tags = {'integration'}
)
