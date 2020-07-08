# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=["*.py", "!global_options.py", "!options_bootstrapper.py", "!*_test.py"],
)

python_library(
  name="global_options",
  sources=["global_options.py"],
)

python_library(
  name="options_bootstrapper",
  sources=["options_bootstrapper.py"],
)

python_tests(
  name="tests",
  sources=['*_test.py', '!*_integration_test.py'],
  timeout=300,
)

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    'testprojects/src/python:plugins_directory',
  ],
  tags = ['integration'],
  timeout=300,
)
