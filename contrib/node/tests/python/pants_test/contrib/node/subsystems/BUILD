# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='subsystems',
  dependencies=[
    ':node_distribution',
  ]
)

python_tests(
  name='node_distribution',
  sources=['test_node_distribution.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/subsystems:node_distribution',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)
