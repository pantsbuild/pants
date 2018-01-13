# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


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
    ':flask_lib'
  ]
)

python_requirement_library(
  name='flask_lib',
  requirements=[
    python_requirement('flask==0.12.1'),
  ]
)
