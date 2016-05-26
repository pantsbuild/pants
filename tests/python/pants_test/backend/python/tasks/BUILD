# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
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
  name='python_task',
  sources=['test_python_task.py'],
  dependencies=[
    ':python_task_test_base',
    'src/python/pants/backend/python/tasks:python',
  ]
)

python_tests(
  name='python_binary_create',
  sources=['test_python_binary_create.py'],
  dependencies=[
    ':python_task_test_base',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:run_info',
  ]
)

python_tests(
  name='pytest_run',
  sources=['test_pytest_run.py'],
  dependencies=[
    '3rdparty/python:coverage',
    '3rdparty/python:pex',
    '3rdparty/python:mock',
    ':python_task_test_base',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/backend/python:python_setup',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:timeout',
  ]
)

python_tests(
  name='python_repl',
  sources=['test_python_repl.py'],
  dependencies=[
    ':python_task_test_base',
        'src/python/pants/backend/python/tasks:python',
    'src/python/pants/backend/python:all_utils',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name='python_repl_integration',
  sources=['test_python_repl_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name='pytest_run_integration',
  sources=['test_pytest_run_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name='setup_py',
  sources=['test_setup_py.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:mock',
    ':python_task_test_base',

    # TODO(John Sirois): XXX this dep needs to be fixed.  All pants/java utility code needs to live
    # in pants java since non-jvm backends depend on it to run things.
    'src/python/pants/backend/jvm/subsystems:jvm',

    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/subsystem:subsystem_utils'
  ],
)
