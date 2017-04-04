# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/jax_ws/src/python/pants/contrib/jax_ws/targets',
    'contrib/jax_ws/src/python/pants/contrib/jax_ws/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.jax_ws',
  description='JAX-WS Pants plugin',
  register_goals=True,
)
