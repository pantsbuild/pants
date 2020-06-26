# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/mypy/src/python/pants/contrib/mypy/tasks',
    'src/python/pants/goal:task_registrar',
  ],
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.mypy',
    description='MyPy static type analyzer',
    register_goals=True,
  ),
  tags = {"partially_type_checked"},
)
