# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='rsc_compile_integration',
  sources=['test_rsc_compile_integration.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  timeout = 400,
  tags = {'integration'},
)


python_tests(
  name = 'rsc_compile',
  sources = ['test_rsc_compile.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks/jvm_compile',
    'src/python/pants/backend/jvm/tasks/jvm_compile/rsc',
    'tests/python/pants_test:task_test_base',
  ],
)
