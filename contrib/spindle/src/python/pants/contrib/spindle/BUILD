# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  sources=['register.py'],
  dependencies=[
    'contrib/spindle/src/python/pants/contrib/spindle/targets',
    'contrib/spindle/src/python/pants/contrib/spindle/tasks',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:task_registrar',
  ],
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.spindle',
    description='Spindle thrift -> scala generator pants plugins.',
    additional_classifiers=[
      'Topic :: Software Development :: Code Generators'
    ]
  )
)
