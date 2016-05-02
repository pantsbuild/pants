# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'targets',
  dependencies = [
    'contrib/node/src/python/pants/contrib/node/targets:node_module',
    'contrib/scalajs/src/python/pants/contrib/scalajs/subsystems',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
  ],
  sources = globs('*.py'),
)
