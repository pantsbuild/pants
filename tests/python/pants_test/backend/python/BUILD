# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='pants_requirement',
  sources=['test_pants_requirement.py'],
  dependencies=[
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:test_base',
  ]
)

python_tests(
  name='python_requirement_list',
  sources=['test_python_requirement_list.py'],
  dependencies=[
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test:test_base'
  ]
)

python_tests(
  name = 'interpreter_cache',
  sources = ['test_interpreter_cache.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:mock',
    '3rdparty/python:pex',
    ':interpreter_selection_utils',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/testutils:git_util',
    'tests/python/pants_test/testutils:pexrc_util',
    'tests/python/pants_test/testutils:py2_compat',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test:test_base',
  ],
  timeout=1200
)

python_tests(
  name='integration',
  sources=globs('*_integration.py'),
  dependencies=[
    ':pants_requirement_integration_test_base',
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_library(
  name='pants_requirement_integration_test_base',
  sources=['pants_requirement_integration_test_base.py'],
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ]
)

python_library(
  name='interpreter_selection_utils',
  sources=['interpreter_selection_utils.py'],
  dependencies=[
    'src/python/pants/util:process_handler',
    '3rdparty/python:future',
  ]
)
