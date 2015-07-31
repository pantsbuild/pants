# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  sources=['register.py'],
  dependencies=[
    'contrib/npm_module/src/python/pants/contrib/npm_module/targets',
    'contrib/npm_module/src/python/pants/contrib/npm_module/tasks',
    'contrib/npm_module/src/python/pants/contrib/npm_module/tasks/transpilers',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/base:build_file_aliases',
  ],
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.npm_module',
    description='Npm Module Tasks',
    additional_classifiers=[
      'Topic :: Software Development :: NPM Module'
    ]
  )
)
