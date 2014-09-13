# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'sitegen',
  sources=['test_sitegen.py'],
  dependencies = [
    'src/python/internal_backend/sitegen:beautifulsoup4',
    'src/python/internal_backend/sitegen:PyYAML',
    'src/python/internal_backend/sitegen/tasks:sitegen',
  ],
)
