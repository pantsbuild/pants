# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='tasks',
  dependencies=[
    ':node_repl',
    ':node_resolve',
    ':node_run',
    ':node_test',
  ]
)

python_library(
  name='node_paths',
  sources=['node_paths.py']
)

python_library(
  name='node_repl',
  sources=['node_repl.py'],
  dependencies = [
    ':node_paths',
    ':node_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
  ],
)

python_library(
  name='node_task',
  sources=['node_task.py'],
  dependencies = [
    'contrib/node/src/python/pants/contrib/node/subsystems:node_distribution',
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_package',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_test',
    'src/python/pants/base:workunit',
    'src/python/pants/task',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name='node_resolve',
  sources=['node_resolve.py'],
  dependencies = [
    ':node_paths',
    ':node_task',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name='node_run',
  sources=['node_run.py'],
  dependencies = [
    ':node_paths',
    ':node_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:contextutil',
  ],
)

python_library(
  name='node_test',
  sources=['node_test.py'],
  dependencies = [
    ':node_paths',
    ':node_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:contextutil',
  ],
)
