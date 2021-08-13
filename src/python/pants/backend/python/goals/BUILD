# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
  timeout=180,
)

python_tests(
  name="integration",
  sources=["*_integration_test.py", "!setup_py_integration_test.py"],
  timeout=480,
)

python_tests(
  name="setup_py_integration",
  sources=["setup_py_integration_test.py"],
  dependencies=["testprojects/src/python:native_directory"],
  timeout=180,
)
