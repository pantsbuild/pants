# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='test_native_engine_logging',
  sources=['test_native_engine_logging.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'tests/python/pants_test/pantsd:pantsd_integration_test_base',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name='test_workunit_label',
  sources=['test_workunit_label.py'],
  dependencies=[
    'src/python/pants/goal:run_tracker',
    'src/python/pants/testutil:int-test',
    'tests/python/pants_test/logging/data:plugin',
  ],
  tags = {'integration', 'partially_type_checked'},
)
