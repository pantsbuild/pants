# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'tasks',
  dependencies = [
    pants(':aapt_gen'),
    pants(':dx_compile_integration'),
  ],
)

python_tests(
  name = 'aapt_gen',
  sources = 'test_aapt_gen.py',
  dependencies = [
    pants('src/python/pants/backend/android/tasks:all'),
  ],
)

python_tests(
  name = 'dx_compile_integration',
  sources = 'test_dx_compile_integration.py',
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ],
)
