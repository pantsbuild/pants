# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/targets',
    'contrib/go/src/python/pants/contrib/go/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.go',
  description='Go language support for pants.',
  build_file_aliases=True,
  register_goals=True,
)
