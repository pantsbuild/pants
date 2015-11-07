# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='targets',
  dependencies=[
    ':node_module',
    ':node_remote_module',
    ':npm_test',
  ]
)

python_library(
  name='node_module',
  sources=['node_module.py'],
  dependencies=[
    ':npm_package',
    'src/python/pants/base:payload',
  ],
)

python_library(
  name='node_remote_module',
  sources=['node_remote_module.py'],
  dependencies=[
    ':npm_package',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
  ],
)

python_library(
  name='npm_package',
  sources=['npm_package.py'],
  dependencies=[
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
  ]
)

python_library(
  name='npm_test',
  sources=['npm_test.py'],
  dependencies=[
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
  ]
)
