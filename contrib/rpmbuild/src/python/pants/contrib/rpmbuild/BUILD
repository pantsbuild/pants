# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/rpmbuild/src/python/pants/contrib/rpmbuild/targets',
    'contrib/rpmbuild/src/python/pants/contrib/rpmbuild/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.rpmbuild',
  description='RPM package builder for pants',
  build_file_aliases=True,
  register_goals=True,
)