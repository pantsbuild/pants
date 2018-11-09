# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    ':buildrefactor'
  ],
  distribution_name='pantsbuild.pants.contrib.buildrefactor',
  description='Plugin to manipulate and refactor BUILD files and targets',
  register_goals=True,
)

python_library(
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/binaries'
  ]
)
