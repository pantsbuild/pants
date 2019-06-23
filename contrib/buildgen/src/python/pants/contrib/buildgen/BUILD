# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  sources=[],
  dependencies=[
    ':build_file_manipulator',
  ],
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.buildgen',
    description='Automatic manipulation of BUILD dependencies based on source analysis.',
    additional_classifiers=[
      'Topic :: Software Development :: Code Generators'
    ]
  )
)


python_library(
  name = 'build_file_manipulator',
  sources = ['build_file_manipulator.py'],
  dependencies = [
    'src/python/pants/build_graph',
  ]
)
