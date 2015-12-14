# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='fetchers',
  sources=['test_fetchers.py'],
  dependencies=[
    '3rdparty/python:mock',
    '3rdparty/python:requests',
    'contrib/go/src/python/pants/contrib/go/subsystems:fetchers',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)

python_tests(
  name='go_distribution',
  sources=['test_go_distribution.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems:go_distribution',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)
