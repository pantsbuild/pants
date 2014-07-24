# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

dependencies(
  name='core',
  dependencies=[
    pants(':setup_confluence'),
    pants(':wrapped_globs'),
  ],
)
python_tests(
  name = 'setup_confluence',
  sources = ['test_setup_confluence.py'],
  dependencies = [
    pants('src/python/pants/backend/core'),
    pants('tests/python/pants_test:base_test'),
  ]
)
python_tests(
  name = 'wrapped_globs',
  sources = ['test_wrapped_globs.py'],
  dependencies = [
    pants('src/python/pants/backend/core'),
    pants('tests/python/pants_test:base_test'),
  ]
)
