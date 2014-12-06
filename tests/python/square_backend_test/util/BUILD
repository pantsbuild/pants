# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


target(
  name='util',
  dependencies=[
    ':exclude_globally',
  ]
)

python_tests(
  name='exclude_globally',
  sources=['test_exclude_globally.py'],
  dependencies=[
    '3rdparty/python/square_backend:pyyaml',
    'src/python/square_backend:plugins',
  ],
)
