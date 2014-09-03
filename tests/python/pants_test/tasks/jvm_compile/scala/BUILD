# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='scala',
  dependencies=[
    ':test_zinc_analysis',
  ],
)

python_tests(
  name='test_zinc_analysis',
  sources=['test_zinc_analysis.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile:scala',
    'src/python/pants/util:contextutil',
  ],
  coverage=[
    'pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis',
    'pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser',
  ]
)
