# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name="tests",
  sources=["*_test.py", "!*integration_test.py"],
  timeout = 120,
)


python_integration_tests(
  name = 'changed_integration',
  sources = ['changed_integration_test.py'],
  dependencies = [
    '//:gitignore',
    'testprojects/src/python:python_targets_directory',
    'testprojects/src/python:sources_directory',
  ],
  uses_pants_run=True,
  timeout = 600,
)
