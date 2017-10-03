# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    ':buildozer'
  ],
  distribution_name='pantsbuild.pants.contrib.buildozer',
  description='Buildozer tool to manipulate and edit BUILD files',
  register_goals=True,
)


python_library(
  name='buildozer',
  sources=['buildozer.py'],
  dependencies = [
    'src/python/pants/goal:task_registrar',
  ]
)
