# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='all',
  dependencies=[
    ':integration',
    ':unit',
  ]
)

target(
  name='integration',
  dependencies=[
    ':node_repl_integration',
    ':npm_resolve_integration',
    ':npm_run_integration',
    ':npm_test_integration',
  ]
)

target(
  name='unit',
  dependencies=[
    ':node_task',
    ':npm_resolve',
  ]
)

python_tests(
  name='node_repl_integration',
  sources=['test_node_repl_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name='npm_resolve_integration',
  sources=['test_npm_resolve_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name='npm_run_integration',
  sources=['test_npm_run_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name='npm_test_integration',
  sources=['test_npm_test_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name='node_task',
  sources=['test_node_task.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:npm_test',
    'contrib/node/src/python/pants/contrib/node/tasks:node_paths',
    'contrib/node/src/python/pants/contrib/node/tasks:node_task',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name='npm_resolve',
  sources=['test_npm_resolve.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:npm_test',
    'contrib/node/src/python/pants/contrib/node/tasks:node_paths',
    'contrib/node/src/python/pants/contrib/node/tasks:npm_resolve',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)
