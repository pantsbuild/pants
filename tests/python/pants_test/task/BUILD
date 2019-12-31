# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'console_task',
  sources = ['test_console_task.py'],
  dependencies = [
    'src/python/pants/task',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'goal_options_mixin_integration',
  sources = ['test_goal_options_mixin_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'tests/python/pants_test/task/echo_plugin:plugin',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name='mutex_task_mixin',
  sources=['test_mutex_task_mixin.py'],
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'simple_codegen_task',
  sources = ['test_simple_codegen_task.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/base:payload',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='scm_publish',
  sources=['test_scm_publish_mixin.py'],
  coverage=['pants.task.scm_publish_mixin'],
  dependencies=[
    'src/python/pants/task',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  sources=['test_task.py'],
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/cache:cache',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='testrunner_task_mixin',
  sources=['test_testrunner_task_mixin.py'],
  dependencies=[
    'src/python/pants/task',
    'src/python/pants/util:process_handler',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='unpack_remote_sources_base',
  sources=['test_unpack_remote_sources_base.py'],
  dependencies=[
    'src/python/pants/task',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)
