# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_dist(
  sources=['setup.py', 'hello.c'],
  setup_requires=[
    'testprojects/pants-plugins/3rdparty/python/pants',
  ],
)

python_binary(
  name='bin',
  source='main.py',
  dependencies=[
    ':distutils_extensions',
  ],
)
