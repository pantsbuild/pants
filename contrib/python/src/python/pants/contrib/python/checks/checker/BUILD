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
    # NB: Dependencies should only come from this directory's own 3rdparty folder.
    'contrib/python/src/python/pants/contrib/python/checks/checker/3rdparty:pycodestyle',
    'contrib/python/src/python/pants/contrib/python/checks/checker/3rdparty:pyflakes',
    'contrib/python/src/python/pants/contrib/python/checks/checker/3rdparty:six',
  ],
  tags = {'partially_type_checked'},
)

python_binary(
  name='bin',
  entry_point='pants.contrib.python.checks.checker.checker:main',
  dependencies=[
    ':checker',
  ],
  tags = {'partially_type_checked'},
)
