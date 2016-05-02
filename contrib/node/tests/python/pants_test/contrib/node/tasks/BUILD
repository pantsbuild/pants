# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='node_repl_integration',
  sources=['test_node_repl_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='node_resolve_integration',
  sources=['test_node_resolve_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='node_run_integration',
  sources=['test_node_run_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='node_test_integration',
  sources=['test_node_test_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='node_task',
  sources=['test_node_task.py'],
  dependencies = [
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_test',
    'contrib/node/src/python/pants/contrib/node/tasks:node_task',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='node_resolve',
  sources=['test_node_resolve.py'],
  dependencies = [
    'contrib/node/src/python/pants/contrib/node/subsystems/resolvers:node_preinstalled_module_resolver',
    'contrib/node/src/python/pants/contrib/node/subsystems/resolvers:npm_resolver',
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_preinstalled_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/tasks:node_paths',
    'contrib/node/src/python/pants/contrib/node/tasks:node_resolve',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)
