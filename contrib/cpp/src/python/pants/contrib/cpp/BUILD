# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/cpp/src/python/pants/contrib/cpp/targets:targets',
    'contrib/cpp/src/python/pants/contrib/cpp/tasks:tasks',
    'contrib/cpp/src/python/pants/contrib/cpp/toolchain:toolchain',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.cpp',
  description='C++ pants plugin.',
  build_file_aliases=True,
  register_goals=True,
)
