# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='node_build',
  sources=['test_node_build.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/tasks:node_build',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
  timeout=30,
)

python_tests(
  name='node_bundle',
  sources=['test_node_bundle.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_bundle',
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/tasks:node_bundle',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
  timeout=30
)

python_tests(
  name='node_bundle_integration',
  sources=['test_node_bundle_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/node:examples_directory',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
  ],
  timeout=880,
  tags={'integration', 'partially_type_checked'},
)

python_tests(
  name='node_repl_integration',
  sources=['test_node_repl_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/node:examples_directory',
  ],
  tags={'integration', 'partially_type_checked'},
)

python_tests(
  name='node_resolve_integration',
  sources=['test_node_resolve_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/node:examples_directory',
    'contrib/node:testprojects_directory',
  ],
  timeout=400,
  tags={'integration', 'partially_type_checked'},
)

python_tests(
  name='node_run_integration',
  sources=['test_node_run_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/node:examples_directory',
  ],
  timeout=400,
  tags={'integration', 'partially_type_checked'},
)

python_tests(
  name='node_test_integration',
  sources=['test_node_test_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/node:examples_directory',
  ],
  timeout=440,
  tags={'integration', 'partially_type_checked'},
)

python_tests(
  name='node_task',
  sources=['test_node_task.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_test',
    'contrib/node/src/python/pants/contrib/node/tasks:node_paths',
    'contrib/node/src/python/pants/contrib/node/tasks:node_task',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='node_resolve',
  sources=['test_node_resolve.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_preinstalled_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_test',
    'contrib/node/src/python/pants/contrib/node/tasks:node_paths',
    'contrib/node/src/python/pants/contrib/node/tasks:node_resolve',
    'contrib/node/src/python/pants/contrib/node/subsystems/resolvers:npm_resolver',
    'contrib/node/src/python/pants/contrib/node/subsystems/resolvers:node_preinstalled_module_resolver',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='node_lint_integration',
  sources=['test_node_lint_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/node:examples_directory',
  ],
  timeout=180,
  tags={'integration', 'partially_type_checked'},
)

python_tests(
  name='node_install_integration',
  sources=['test_node_install_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/node:examples_directory',
  ],
  timeout=180,
  tags={'integration', 'partially_type_checked'},
)

python_tests(
  name='node_resolve_src_deps',
  sources=['test_node_resolve_src_deps.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_preinstalled_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_test',
    'contrib/node/src/python/pants/contrib/node/tasks:node_paths',
    'contrib/node/src/python/pants/contrib/node/tasks:node_resolve',
    'contrib/node/src/python/pants/contrib/node/subsystems/resolvers:npm_resolver',
    'contrib/node/src/python/pants/contrib/node/subsystems/resolvers:node_preinstalled_module_resolver',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
)
