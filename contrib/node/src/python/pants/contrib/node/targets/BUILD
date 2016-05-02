# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='targets',
  dependencies=[
    ':node_module',
    ':node_preinstalled_module',
    ':node_remote_module',
    ':node_test',
  ]
)

python_library(
  name='node_module',
  sources=['node_module.py'],
  dependencies = [
    ':node_package',
    'src/python/pants/base:payload',
  ],
)

python_library(
  name='node_preinstalled_module',
  sources=['node_preinstalled_module.py'],
  dependencies = [
    ':node_module',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
  ],
)

python_library(
  name='node_remote_module',
  sources=['node_remote_module.py'],
  dependencies = [
    ':node_package',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
  ],
)

python_library(
  name='node_package',
  sources=['node_package.py'],
  dependencies = [
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
  ],
)

python_library(
  name='node_test',
  sources=['node_test.py'],
  dependencies = [
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
  ],
)
