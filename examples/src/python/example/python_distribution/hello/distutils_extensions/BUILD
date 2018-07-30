# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_dist(
  sources=['setup.py', 'hello.c'],
  # FIXME: setup_requires needs to provide transitive deps of all the requested packages too!
  # setup_requires=[
  #   'testprojects/pants-plugins/3rdparty/python/pants',
  # ],
)

python_binary(
  name='bin',
  source='main.py',
  dependencies=[
    ':distutils_extensions',
  ],
)
