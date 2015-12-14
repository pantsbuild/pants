# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/spindle/src/python/pants/contrib/spindle/targets',
    'contrib/spindle/src/python/pants/contrib/spindle/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.spindle',
  description='Spindle thrift -> scala generator pants plugins.',
  additional_classifiers=[
    'Topic :: Software Development :: Code Generators'
  ],
  build_file_aliases=True,
  register_goals=True,
)
