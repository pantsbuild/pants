# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name="testprojects_integration",
  sources=['test_testprojects_integration.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test:test_base',
  ],
  tags = {'integration'},
  timeout=950,
)
