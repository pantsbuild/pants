# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
  timeout=180,
)


python_integration_tests(
  name='integration',
  timeout=480,
)
