# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This BUILD file is intended to be an example of python 3 compatible targets and
# to serve as a set of test cases for interpreter selection based on different targets.
# To successfully build and run this binary target, the user will need to define a 
# .pexrc file in /etx/pexrc, ~/.pexrc, or in a .pexrc in the pants root dir. The pexrc 
# will need to contain a PEX_PYTHON_PATH variable containing an absolute path to a 
# python 3 interpreter.
#
# An example of a PEX_PYTHON_PATH variable in a pexrc:
# 	PEX_PYTHON_PATH=/path/to/python2.7:/path/to/python3.6
#
# Note that the basename of the python binaries specified must either be 'python' or 
# 'pythonX.Y'. Specifying only major version (i.e. python3) will be ignored by Pants 
# interpreter filtration.
# 

python_binary(
  name='main_py3',
  sources=['main_py3.py'],
  compatibility=['CPython>3'],
  dependencies=[
    # We depend on libraries with both narrow and wide ranges in order to confirm that the narrower
    # range is the one selected.
    ':lib_py3',
    ':lib_py23',
  ],
  tags={"nolint"},
)

python_library(
  name='lib_py3',
  sources=['lib_py3.py'],
  compatibility=['CPython>3'],
  tags={"nolint"},
)

python_tests(
  name='test_py3',
  sources=[
    'test_py3.py',
  ],
  dependencies=[
    ':main_py3'
  ],
  compatibility=['CPython>3'],
  tags={"nolint"},
)

python_binary(
  name='main_py2',
  sources=['main_py2.py'],
  compatibility=['CPython>2.7.6,<3'],
  dependencies=[
    # We depend on libraries with both narrow and wide ranges in order to confirm that the narrower
    # range is the one selected.
    ':lib_py2',
    ':lib_py23',
  ],
  tags={"nolint"},
)

python_library(
  name='lib_py2',
  sources=['lib_py2.py'],
  compatibility=['CPython>2.7.6,<3'],
  tags={"nolint"},
)

python_tests(
  name='test_py2',
  sources=[
    'test_py2.py',
  ],
  dependencies=[
    ':main_py2'
  ],
  compatibility=['CPython>2.7.6,<3'],
  tags={"nolint"},
)

python_binary(
  name='main_py23',
  sources=['main_py23.py'],
  compatibility=['CPython>2.7'],
  dependencies=[
    ':lib_py23'
  ],
  tags={"nolint"},
)

python_library(
  name='lib_py23',
  sources=['lib_py23.py'],
  compatibility=['CPython>2.7'],
  tags={"nolint"},
)

python_tests(
  name='test_py23',
  sources=[
    'test_py23.py',
  ],
  dependencies=[
    ':main_py23'
  ],
  compatibility=['CPython>2.7'],
  tags={"nolint"},
)
