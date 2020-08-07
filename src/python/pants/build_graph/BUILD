# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name="tests",
  sources=["*_test.py", "!*_integration_test.py"],
)

python_integration_tests(
  name='integration',
  uses_pants_run=True,
  timeout=90,
)
