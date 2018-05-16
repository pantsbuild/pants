# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/confluence/src/python/pants/contrib/confluence/tasks',
    'contrib/confluence/src/python/pants/contrib/confluence/util',
    'src/python/pants/build_graph',
  ],
  distribution_name='pantsbuild.pants.contrib.confluence',
  description='Confluence pants plugin',
  register_goals=True,
)
