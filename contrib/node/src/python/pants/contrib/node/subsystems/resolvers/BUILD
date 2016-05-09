# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='resolvers',
  dependencies=[
    ':npm_resolver',
    ':node_preinstalled_module_resolver',
  ]
)

python_library(
  name='npm_resolver',
  sources=['npm_resolver.py'],
  dependencies = [
    ':node_resolver_base',
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/node/src/python/pants/contrib/node/tasks:node_resolve',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
  ],
)

python_library(
  name='node_preinstalled_module_resolver',
  sources=['node_preinstalled_module_resolver.py'],
  dependencies = [
    '3rdparty/python:six',
    ':node_resolver_base',
    'contrib/node/src/python/pants/contrib/node/targets:node_preinstalled_module',
    'contrib/node/src/python/pants/contrib/node/tasks:node_resolve',
    'src/python/pants/base:exceptions',
    'src/python/pants/fs',
    'src/python/pants/net',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
  ],
)

python_library(
  name='node_resolver_base',
  sources=['node_resolver_base.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta',
  ],
)
