# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='interpreter_cache_test_mixin',
  sources=['interpreter_cache_test_mixin.py'],
  dependencies = [
    '3rdparty/python:future',
  ]
)

python_library(
  name='python_task_test_base',
  sources=['python_task_test_base.py'],
  dependencies=[
    ':interpreter_cache_test_mixin',
    '3rdparty/python:future',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/build_graph',
    'tests/python/pants_test:task_test_base'
  ]
)

python_native_code_test_files = [
  'test_build_local_python_distributions.py',
  'test_python_distribution_integration.py',
  'test_ctypes_integration.py',
]

python_tests(
  name='python_native_code_testing',
  sources=python_native_code_test_files,
  dependencies=[
    ':python_task_test_base',
    '3rdparty/python:future',
    'src/python/pants/backend/native',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/engine:scheduler_test_base',
  ],
  tags={'platform_specific_behavior', 'integration'},
  timeout=2400,
)

python_tests(
  sources=globs('test_*.py', exclude=([globs('*_integration.py')] + python_native_code_test_files)),
  dependencies=[
    ':python_task_test_base',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:future',
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
    'src/python/pants/source',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/engine:scheduler_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:task_test_base',
    'tests/python/pants_test/tasks:task_test_base',
  ],
  timeout=600
)


python_tests(
  name='integration',
  sources=globs('*_integration.py', exclude=python_native_code_test_files),
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python:pants_requirement_integration_test_base',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
  ],
  tags={'integration'},
  timeout=2400
)

python_tests(
  name='isort_run_integration',
  sources=['test_isort_run_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
  ],
  tags={'integration'},
)

python_tests(
  name='isort_run',
  sources=['test_isort_run.py'],
  dependencies=[
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:task_test_base',
  ],
  timeout=300
)
