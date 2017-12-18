# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/avro/src/python/pants/contrib/avro/targets',
    'contrib/avro/src/python/pants/contrib/avro/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.avro',
  description='Avro Java code generation support for pants',
  build_file_aliases=True,
  register_goals=True,
)
