# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: This contrib module must keep Python 2 and Python 3 compatibility, as the binary is ran
# with the interpreter corresponding to the version of the code being checked. Consequently,
# we mark this contrib package as universal in packages.py, and must keep Python 2 support despite
# Pants overall requiring Python 3.

python_library(
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.python.checks.checker',
    description='The Pants Python source code lint tool.',
    entry_points={
      'console_scripts': ['checker = pants.contrib.python.checks.checker.checker:main']
    }
  ),
  dependencies=[
    # NB: See https://github.com/pantsbuild/pants/issues/7158 before introducing additional
    # dependencies here.
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
