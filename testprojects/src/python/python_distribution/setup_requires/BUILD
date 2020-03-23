# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_dist(
  name='checksummed_version_dist',
  setup_requires=[
    # NB: This particular requirement is selected because it is unlikely to already be available to
    # the python interpreter.
    'testprojects/3rdparty/python:checksumdir',
  ],
)

# NB: The default `sources` for this target is 'test_*.py', so its default sources don't intersect
# with the `python_dist()`'s default sources.
python_tests(
  name='tests',
  dependencies=[
    ':checksummed_version_dist',
  ],
)
