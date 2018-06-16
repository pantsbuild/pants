# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/native/src/python/pants/contrib/native/subsystems',
    'contrib/native/src/python/pants/contrib/native/tasks',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.native',
  description='C/C++ support for pants.',
  register_goals=True,
)
