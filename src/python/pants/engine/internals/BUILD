# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=['*.py', '!*_test.py']
)

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
  timeout=90,
)

python_integration_tests(
  name='integration',
  uses_pants_run=True,
  dependencies=[
    'pants-plugins/internal_plugins/rules_for_testing',
    'testprojects/src/python:hello_directory',
  ],
  timeout=180,
)

python_library(
  name='native',
  sources=['native_engine.pyi'],
  dependencies=[':native_engine'],
)

resources(
  name='native_engine',
  sources=['native_engine.so', 'native_engine.so.metadata'],
)

resources(
  name='fs_test_data',
  sources=['fs_test_data/fs_test.tar', 'fs_test_data/tls/rsa/*']
)
