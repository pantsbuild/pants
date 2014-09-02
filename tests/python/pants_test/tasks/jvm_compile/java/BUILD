# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='java',
  dependencies=[
    ':test_java_compile_integration',
  ],
)

python_tests(
  name='test_java_compile_integration',
  sources=['test_java_compile_integration.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile:java',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/base:context_utils',
  ],
  coverage=[
    'pants.backend.jvm.tasks.jvm_compile.java',
  ]
)
