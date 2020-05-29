# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    ':target_types',
    'contrib/go/src/python/pants/contrib/go/targets',
    'contrib/go/src/python/pants/contrib/go/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  tags = {'partially_type_checked'},
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.go',
    description='Go language support for pants.',
    build_file_aliases=True,
    register_goals=True,
    target_types=True,
  )
)

python_library(
  name='target_types',
  sources=['target_types.py'],
  dependencies=[
    'src/python/pants/engine:target',
  ],
  tags = {"type_checked"},
)
