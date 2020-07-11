# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=['*.py', '!native.py', '!*_test.py']
)

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
)

python_integration_tests(
  name='integration',
  uses_pants_run=True,
  dependencies=[
    'examples/src/python/example:hello_directory',
  ],
)

python_library(
  name='native',
  sources=['native.py'],
  dependencies=[
    ':native_engine',
  ],
)

resources(
  name='native_engine',
  sources=[
    'native_engine.so',
    'native_engine.so.metadata',
  ],
)
