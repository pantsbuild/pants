# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello world, but built with a python_dist.
# python_dist allows you to use setup.py to depend on C/C++ extensions.

python_dist(
  name='superhello',
  sources=[
    'super_greet.c',
    'hello_package/hello.py',
    'hello_package/__init__.py',
    'setup.py'
  ]
)

python_binary(
  name='main',
  source='main.py',
  dependencies=[
    ':superhello',
  ]
)

# The targets below are for testing purposes only.
# Their purpose is to expose an error that arises when a python_dist
# contains a requirement that conflicts with the same requirement of
# a different version in the consuming target. In this case, the pants
# goal will fail and indicate that incomptible requirements exist.

python_dist(
  name='superhello_with_conflicting_dep',
  sources=[
    'super_greet.c',
    'hello_package/hello.py',
    'hello_package/__init__.py',
    'setup.py'
  ],
  dependencies=[
    ':pex_lib'
  ]
)

python_binary(
  name='main_with_conflicting_dep',
  source='main.py',
  dependencies=[
    ':superhello_with_conflicting_dep',
    '3rdparty/python:pex'
  ]
)

python_requirement_library(
  name='pex_lib',
  requirements=[
    python_requirement('pex==1.2.11'),
  ]
)
