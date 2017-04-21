# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/kythe/src/python/pants/contrib/kythe/tasks',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.kythe',
  description='Kythe support for pants.',
  register_goals=True,
)
