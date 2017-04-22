# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  dependencies=[
    ':node_build',
    ':node_bundle',
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
  name='node_build',
  sources=['node_build.py'],
  dependencies=[
    ':node_paths',
    ':node_task',
    'src/python/pants/base:workunit',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
  ]
)

python_library(
  name='node_bundle',
  sources=['node_bundle.py'],
  dependencies=[
    ':node_paths',
    ':node_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/fs',
    'src/python/pants/util:dirutil',
  ]
)

python_library(
  name='node_repl',
  sources=['node_repl.py'],
  dependencies=[
    ':node_paths',
    ':node_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
  ]
)

python_library(
  name='node_task',
  sources=['node_task.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/subsystems:node_distribution',
    'contrib/node/src/python/pants/contrib/node/targets:node_bundle',
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_remote_module',
    'contrib/node/src/python/pants/contrib/node/targets:node_package',
    'contrib/node/src/python/pants/contrib/node/targets:node_test',
    'src/python/pants/base:workunit',
    'src/python/pants/task',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='node_resolve',
  sources=['node_resolve.py'],
  dependencies=[
    ':node_paths',
    ':node_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
  ]
)

python_library(
  name='node_run',
  sources=['node_run.py'],
  dependencies=[
    ':node_paths',
    ':node_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:contextutil',
  ]
)

python_library(
  name='node_test',
  sources=['node_test.py'],
  dependencies=[
    ':node_paths',
    ':node_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
  ]
)
