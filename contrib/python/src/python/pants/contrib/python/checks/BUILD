# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/python/src/python/pants/contrib/python/checks/tasks/checkstyle:all',
    'contrib/python/src/python/pants/contrib/python/checks/tasks:python',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.python.checks',
  description='Additional python lints and checks.',
  register_goals=True,
)
