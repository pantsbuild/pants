# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

dependencies(
  name='core',
  dependencies=[
    ':setup_confluence',
    ':wrapped_globs',
  ],
)
python_tests(
  name = 'setup_confluence',
  sources = ['test_setup_confluence.py'],
  dependencies = [
    'src/python/pants/backend/core',
    'tests/python/pants_test:base_test',
  ]
)
python_tests(
  name = 'wrapped_globs',
  sources = ['test_wrapped_globs.py'],
  dependencies = [
    'src/python/pants/backend/core',
    'tests/python/pants_test:base_test',
  ]
)
