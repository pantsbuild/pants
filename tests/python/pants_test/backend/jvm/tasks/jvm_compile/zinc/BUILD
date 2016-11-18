# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name='zinc_compile_integration_base',
  sources=['zinc_compile_integration_base.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
  ],
)

python_tests(
  name='zinc_compile_integration_with_zjars',
  sources=['test_zinc_compile_integration_with_zjars.py'],
  dependencies=[
    ':zinc_compile_integration_base',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  timeout = 240,
  tags = {'integration'},
)

python_tests(
  name='zinc_compile_integration',
  sources=['test_zinc_compile_integration.py'],
  dependencies=[
    ':zinc_compile_integration_base',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  timeout = 240,
  tags = {'integration'},
)
