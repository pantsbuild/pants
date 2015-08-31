# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO(John Sirois): Tie this into the contrib/release_packages.sh the minute the plugin can do
# one useful thing, for example `./pants test contrib/node/examples::`.
contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/node/src/python/pants/contrib/node/targets',
    'contrib/node/src/python/pants/contrib/node/tasks',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.node',
  description='Node.js support for pants.',
  build_file_aliases=True,
  register_goals=True,
)
