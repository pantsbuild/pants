# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='jvm_compile',
  dependencies=[
    ':cache_hit_callback',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile/java',
  ],
)

python_tests(
  name='cache_hit_callback',
  sources=['test_cache_hit_callback.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name='base_compile_integration_test',
  sources=['base_compile_integration_test.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ]
)
