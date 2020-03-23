# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=['googlejavaformat.py', 'subsystem.py'],
  tags = {'partially_type_checked'},
)

contrib_plugin(
  name='plugin',
  dependencies=[
    ':googlejavaformat',
    'src/python/pants/goal:task_registrar',
  ],
  tags = {'partially_type_checked'},
  distribution_name='pantsbuild.pants.contrib.googlejavaformat',
  description='Google Java Format code formatter pants plugins.',
  additional_classifiers=[
    'Topic :: Software Development :: Pre-processors'
  ],
  register_goals=True,
)
