# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:dataclasses',
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    ':plugins',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_root',
    'src/python/pants/base:exception_sink',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/binaries',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/engine/internals:build_files',
    'src/python/pants/engine/internals:core_abstractions',
    'src/python/pants/engine/internals:graph',
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine/internals:options_parsing',
    'src/python/pants/engine/internals:scheduler',
    'src/python/pants/engine/legacy:address_mapper',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:parser',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/engine:console',
    'src/python/pants/engine:platform',
    'src/python/pants/engine:unions',
    'src/python/pants/goal',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/option:global_options',
    'src/python/pants/option:options_bootstrapper',
    'src/python/pants/process',
    'src/python/pants/python',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:logging',
    'src/python/pants/util:memo',
    'src/python/pants/util:ordered_set',
    'src/python/pants:version',
  ],
  tags = {'partially_type_checked'},
)

target(
  name='plugins',
  dependencies=[
    'src/python/pants/backend/awslambda/python',
    'src/python/pants/backend/codegen/protobuf/python',
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/docgen:plugin',
    'src/python/pants/backend/graph_info:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/pants_info',
    'src/python/pants/backend/project_info',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/lint/bandit',
    'src/python/pants/backend/python/lint/black',
    'src/python/pants/backend/python/lint/docformatter',
    'src/python/pants/backend/python/lint/flake8',
    'src/python/pants/backend/python/lint/isort',
    'src/python/pants/backend/python/lint/pylint',
    'src/python/pants/backend/native',
    'src/python/pants/core:plugin',
  ],
)

python_library(
  name = 'util',
  sources = ['util.py'],
  dependencies=[
    ':init',
    'src/python/pants/testutil:test_base'
  ]
)
