# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    ':buildozer'
  ],
  distribution_name='pantsbuild.pants.contrib.buildrefactor',
  description='Plugin to manipulate and refactor BUILD files and targets',
  register_goals=True,
)


python_library(
  name='buildozer',
  sources=['buildozer.py'],
  dependencies = [
    'src/python/pants/binaries:binary_util'
  ]
)


python_library(
  name='meta_rename',
  sources=['meta_rename.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:scala'
  ]
)
