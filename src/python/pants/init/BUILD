# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    ':plugins',
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    '3rdparty/python:wheel',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants:version',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/engine:native',
    'src/python/pants/engine/legacy:change_calculator',
    'src/python/pants/goal',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/logging',
    'src/python/pants/option',
    'src/python/pants/process',
    'src/python/pants/python',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ]
)

target(
  name='plugins',
  dependencies=[
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/docgen:plugin',
    'src/python/pants/backend/graph_info:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/project_info:plugin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python_old:plugin',
  ],
)
