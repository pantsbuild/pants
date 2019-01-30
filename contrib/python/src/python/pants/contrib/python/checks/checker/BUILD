# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.python.checks.checker',
    description='The Pants Python source code lint tool.',
    entry_points={
      'console_scripts': ['checker = pants.contrib.python.checks.checker.checker:main']
    }
  ),
  dependencies=[
    '3rdparty/python:pycodestyle',
    '3rdparty/python:pyflakes',
    '3rdparty/python:six',
  ]
)

python_binary(
  name='bin',
  entry_point='pants.contrib.python.checks.checker.checker:main',
  dependencies=[
    ':checker',
  ]
)
