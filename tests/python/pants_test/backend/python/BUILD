# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='python',
  dependencies=[
    ':test_python_chroot',
    'tests/python/pants_test/backend/python/targets',
    'tests/python/pants_test/backend/python/tasks'
  ]
)

python_tests(
  name='test_python_chroot',
  sources=['test_python_chroot.py'],
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/backend/python:python_chroot',
  ]
)
