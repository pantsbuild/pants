# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='scm',
  dependencies=[
    ':test_git',
  ]
)

python_tests(
  name='test_git',
  sources=['test_git.py'],
  dependencies=[
    'src/python/pants/scm',
    'src/python/pants/scm:git',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  coverage=[
    'pants.scm.git',
  ]
)
