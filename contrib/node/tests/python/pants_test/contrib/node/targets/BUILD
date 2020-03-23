# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='node_remote_module',
  sources=['test_node_remote_module.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'src/python/pants/testutil:test_base'
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='node_package',
  sources=['test_node_package.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_package',
    'src/python/pants/testutil:test_base'
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='node_module',
  sources=['test_node_module.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'src/python/pants/testutil:test_base'
  ],
  tags = {'partially_type_checked'},
)
