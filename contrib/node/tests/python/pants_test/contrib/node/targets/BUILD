# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='targets',
  dependencies=[
    ':node_package',
    ':node_remote_module',
  ]
)

python_tests(
  name='node_remote_module',
  sources=['test_node_remote_module.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'tests/python/pants_test:base_test'
  ]
)

python_tests(
  name='node_package',
  sources=['test_node_package.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_package',
    'tests/python/pants_test:base_test'
  ]
)
