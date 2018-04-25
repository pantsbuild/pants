# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='interpreter_cache_test_mixin',
  sources=['interpreter_cache_test_mixin.py'],
)

python_library(
  name='python_task_test_base',
  sources=['python_task_test_base.py'],
  dependencies=[
    ':interpreter_cache_test_mixin',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base'
  ]
)

python_tests(
  sources=globs('test_*.py', exclude=[globs('*_integration.py')]),
  dependencies=[
    ':python_task_test_base',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:coverage',
    '3rdparty/python:mock',
    '3rdparty/python:pex',
    'src/python/pants/backend/native',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/base:build_root',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:run_info',
    'src/python/pants/build_graph',
    'src/python/pants/fs',
    'src/python/pants/python',
    'src/python/pants/source',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/engine:scheduler_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/tasks:task_test_base',
  ],
  timeout=300
)


python_tests(
  name='integration',
  sources=globs('*_integration.py'),
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/backend/python:pants_requirement_integration_test_base',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=2400
)

python_tests(
  name='python_isort_integration',
  sources=['test_python_isort_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
  ],
  tags={'integration'},
)

python_tests(
  name='python_isort',
  sources=['test_python_isort.py'],
  dependencies=[
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/tasks:task_test_base',
  ],
  timeout=300
)
