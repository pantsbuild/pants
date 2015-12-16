# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/haskell/src/python/pants/contrib/haskell/tasks:tasks',
    'contrib/haskell/src/python/pants/contrib/haskell/targets:targets',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.haskell',
  description='Haskell pants plugin',
  build_file_aliases=True,
  register_goals=True,
)
