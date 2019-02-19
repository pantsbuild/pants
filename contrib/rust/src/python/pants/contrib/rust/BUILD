# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/rust/src/python/pants/contrib/rust/targets',
    'contrib/rust/src/python/pants/contrib/rust/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar'
  ],
  distribution_name='pantsbuild.pants.contrib.rust',
  description='Rust support for pants.',
  build_file_aliases=True,
  register_goals=True
)
