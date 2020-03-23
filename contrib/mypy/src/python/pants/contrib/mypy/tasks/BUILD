# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    '3rdparty/python:pex',
    'src/python/pants/util:process_handler',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/build_graph',
    'contrib/mypy/src/python/pants/contrib/mypy/subsystems',
  ],
  tags = {"partially_type_checked"},
)
