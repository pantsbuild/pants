# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/codeanalysis/src/python/pants/contrib/codeanalysis/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.codeanalysis',
    description='Support for various code analysis tools in Pants.',
    register_goals=True,
  ),
  tags = {"partially_type_checked"},
)
