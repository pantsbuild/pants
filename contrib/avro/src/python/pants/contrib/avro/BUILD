# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  sources=['register.py', '__init__.py'],
  dependencies=[
    ':target_types',
    'contrib/avro/src/python/pants/contrib/avro/targets',
    'contrib/avro/src/python/pants/contrib/avro/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.avro',
  description='Avro Java code generation support for pants (deprecated)',
  build_file_aliases=True,
  register_goals=True,
  target_types=True,
  tags = {"partially_type_checked"},
)

python_library(
  name='target_types',
  sources=['target_types.py'],
  dependencies=[
    'src/python/pants/backend/jvm:target_types',
    'src/python/pants/engine:target',
  ],
  tags = {"type_checked"},
)
