# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/scrooge/src/python/pants/contrib/scrooge/tasks',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.scrooge',
  description='Scrooge thrift generator pants plugins.',
  additional_classifiers=[
    'Topic :: Software Development :: Code Generators'
  ],
  register_goals=True,
)
