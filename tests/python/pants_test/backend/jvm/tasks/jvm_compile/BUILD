# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='jvm_compile',
  dependencies=[
    ':resource_mapping',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile/java',
  ],
)

python_tests(
  name = 'resource_mapping',
  sources = ['test_resource_mapping.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:resource_mapping',
    'tests/python/pants_test:base_test',
  ],
  resources=rglobs('test-data/*'),
)

python_library(
  name='base_compile_integration_test',
  sources=['base_compile_integration_test.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ]
)
