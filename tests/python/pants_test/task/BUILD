# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'console_task',
  sources = ['test_console_task.py'],
  dependencies = [
    'src/python/pants/task',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='mutex_task_mixin',
  sources=['test_mutex_task_mixin.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='scm_publish',
  sources=['test_scm_publish_mixin.py'],
  coverage=['pants.task.scm_publish_mixin'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/task',
  ],
)

python_tests(
  name='task',
  sources=['test_task.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:payload',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='testrunner_task_mixin',
  sources=['test_testrunner_task_mixin.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
    'src/python/pants/util:process_handler',
    'src/python/pants/util:timeout',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)
