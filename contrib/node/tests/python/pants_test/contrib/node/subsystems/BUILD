# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='node_distribution',
  sources=['test_node_distribution.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/subsystems',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/base:context_utils',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)

python_tests(
  name='package_managers',
  sources=['test_package_managers.py'],
  dependencies=[
    '3rdparty/python:mock',
    'contrib/node/src/python/pants/contrib/node/subsystems',
  ]
)
