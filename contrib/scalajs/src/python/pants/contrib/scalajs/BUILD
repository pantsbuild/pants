# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    ':target_types',
    'contrib/node/src/python/pants/contrib/node:plugin',
    'contrib/scalajs/src/python/pants/contrib/scalajs/subsystems',
    'contrib/scalajs/src/python/pants/contrib/scalajs/targets',
    'contrib/scalajs/src/python/pants/contrib/scalajs/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  tags = {'partially_type_checked'},
  distribution_name='pantsbuild.pants.contrib.scalajs',
  description='scala.js support for pants (deprecated).',
  build_file_aliases=True,
  register_goals=True,
  global_subsystems=True,
  target_types=True,
)

python_library(
  name='target_types',
  sources=['target_types.py'],
  dependencies=[
    'contrib/node/src/python/pants/contrib/node:target_types',
    'src/python/pants/engine:target',
  ],
  tags = {"type_checked"},
)
