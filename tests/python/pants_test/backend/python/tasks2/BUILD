# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  sources=globs('test_*.py', exclude=[globs('*_integration.py')]),
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:coverage',
    '3rdparty/python:mock',
    '3rdparty/python:pex',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks2',
    'src/python/pants/base:build_root',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:run_info',
    'src/python/pants/build_graph',
    'src/python/pants/fs',
    'src/python/pants/python',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils'
  ]
)


python_tests(
  name='integration',
  sources=globs('*_integration.py'),
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
