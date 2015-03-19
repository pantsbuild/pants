# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='scala',
  dependencies=[
    ':scala_compile_integration',
    ':zinc_analysis',
  ],
)

python_tests(
  name='scala_compile_integration',
  sources=['test_scala_compile_integration.py'],
  dependencies=[
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ]
)

python_tests(
  name='zinc_analysis',
  sources=['test_zinc_analysis.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile:scala',
    'src/python/pants/util:contextutil',
  ]
)
