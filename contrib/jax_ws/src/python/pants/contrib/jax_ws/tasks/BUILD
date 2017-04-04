# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=[
    'jax_ws_gen.py',
  ],
  dependencies=[
    'contrib/jax_ws/src/python/pants/contrib/jax_ws/targets:targets',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ]
)
