# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_*.py', '!*_integration.py'],
  dependencies=[
    'src/python/pants/backend/native',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:build_root',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:run_info',
    'src/python/pants/build_graph',
    'src/python/pants/fs',
    'src/python/pants/engine/internals:scheduler_test_base',
    'src/python/pants/source',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/python/tasks/util',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:interpreter_selection_utils',
    'src/python/pants/testutil:task_test_base',
  ],
  tags={'platform_specific_behavior', 'partially_type_checked'},
  timeout=600,
)

python_tests(
  name='integration',
  sources=['*_integration.py'],
  dependencies=[
    'src/python/pants/backend/native',
    'src/python/pants/backend/native/targets',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/engine/internals:scheduler_test_base',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'src/python/pants/util:enums',
    'tests/python/pants_test/backend/python/tasks/util',
    'testprojects/src/python:python_distribution_directory',
  ],
  tags={'platform_specific_behavior', 'integration', 'partially_type_checked'},
  timeout=900,
)
