# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='pants_requirement',
  sources=['test_pants_requirement.py'],
  dependencies=[
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/python',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='python_requirement_list',
  sources=['test_python_requirement_list.py'],
  dependencies=[
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/python',
    'src/python/pants/testutil:test_base'
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'interpreter_cache',
  sources = ['test_interpreter_cache.py'],
  dependencies = [
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:pexrc_util',
    'src/python/pants/testutil:interpreter_selection_utils',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='integration',
  sources=['*_integration.py'],
  dependencies=[
    ':pants_requirement_integration_test_base',
    'src/python/pants/base:build_environment',
    'src/python/pants/testutil:int-test',
    'examples/tests/python/example_test:hello_directory',
    'testprojects:pants_plugins_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout = 120,
)

python_library(
  name='pants_requirement_integration_test_base',
  sources=['pants_requirement_integration_test_base.py'],
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
  ],
  tags = {'partially_type_checked'},
)
