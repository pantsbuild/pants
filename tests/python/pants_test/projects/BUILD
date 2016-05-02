# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='examples_integration',
  sources=['test_examples_integration.py'],
  dependencies = [
    ':base',
  ],
  tags = {'integration'},
)

python_tests(
  name='testprojects_integration',
  timeout=600,
  sources=['test_testprojects_integration.py'],
  dependencies = [
    ':base',
  ],
  tags = {'integration'},
)

python_library(
  name='base',
  sources=['base_project_integration_test.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
)
