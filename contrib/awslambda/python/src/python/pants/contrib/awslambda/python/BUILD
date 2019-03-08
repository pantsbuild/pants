# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/awslambda/python/src/python/pants/contrib/awslambda/python/subsystems',
    'contrib/awslambda/python/src/python/pants/contrib/awslambda/python/targets',
    'contrib/awslambda/python/src/python/pants/contrib/awslambda/python/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.awslambda_python',
  description='Pants plugin for creating deployable AWS Lambdas out of python code.',
  build_file_aliases=True,
  register_goals=True,
)
