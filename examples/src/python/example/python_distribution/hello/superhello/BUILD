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
