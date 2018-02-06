# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_dist(
  name='fasthello',
  sources=[
    'super_greet.c',
    'hello_package/hello.py',
    'hello_package/__init__.py',
    'setup.py'
  ]
)

python_binary(
  name='main_with_no_conflict',
  source='main.py',
  dependencies=[
    ':fasthello',
  ]
)

python_binary(
  name='main_with_conflicting_dep',
  source='main.py',
  dependencies=[
    ':fasthello',
    ':pycountry'
  ]
)

python_requirement_library(
  name='pycountry',
  requirements=[
    python_requirement('pycountry==17.9.23'),
  ]
)

python_binary(
  name='main_with_no_pycountry',
  source='main.py'
)
