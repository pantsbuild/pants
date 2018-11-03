# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=globs('*.py', exclude=['test_native_engine_logging.py', 'test_workunit_label.py']),
  dependencies=[
    '3rdparty/python:six',
    'src/python/pants/util:contextutil',
  ],
)

python_tests(
  name='test_native_engine_logging',
  sources=[
    'test_native_engine_logging.py'
  ],
  dependencies=[
    'tests/python/pants_test:int-test',
    'tests/python/testutils:py2_compat',
  ],
  tags = {'integration'},
)

python_tests(
  name='test_workunit_label',
  sources=[
    'test_workunit_label.py'
  ],
  dependencies=[
    'src/python/pants/goal:run_tracker',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
