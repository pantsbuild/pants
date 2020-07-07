# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
  timeout=180,
)


python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  tags=['integration'],
  timeout=480,
)
