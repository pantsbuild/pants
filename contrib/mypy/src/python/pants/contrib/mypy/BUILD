# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/util:process_handler',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/option',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.mypy',
  description='MyPy static type analyzer',
  register_goals=True,
)
