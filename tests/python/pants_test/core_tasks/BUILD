# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='bash_completion',
  sources=['test_bash_completion.py'],
  coverage=['pants.core_tasks.bash_completion'],
  dependencies=[
    '3rdparty/python:mock',
    'src/python/pants/core_tasks',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'list_goals',
  sources = ['test_list_goals.py'],
  dependencies = [
    'src/python/pants/core_tasks',
    'src/python/pants/goal',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'run_prep_command',
  sources = ['test_run_prep_command.py'],
  dependencies = [
    '3rdparty/python:six',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'roots',
  sources = ['test_roots.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/core_tasks',
    'src/python/pants/source',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'what_changed',
  sources = ['test_what_changed.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/goal:workspace',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)
