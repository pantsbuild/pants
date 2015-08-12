# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  sources=['register.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/targets',
    'contrib/go/src/python/pants/contrib/go/tasks',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:task_registrar',
  ],
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.go',
    description='Go language support for pants.',
  )
)
