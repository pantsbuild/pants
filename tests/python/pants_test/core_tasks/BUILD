# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='bash_completion',
  sources=['test_bash_completion.py'],
  coverage=['pants.core_tasks.bash_completion'],
  dependencies=[
    '3rdparty/python:mock',
    'src/python/pants/core_tasks',
    'tests/python/pants_test:task_test_base',
  ]
)

python_tests(
  name = 'deferred_sources_mapper_integration',
  sources = ['test_deferred_sources_mapper_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'list_goals',
  sources = ['test_list_goals.py'],
  dependencies = [
    'src/python/pants/core_tasks',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/task',
    'tests/python/pants_test:task_test_base',
  ],
)

python_tests(
  name = 'prep_command_integration',
  sources = ['test_prep_command_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'run_prep_command',
  sources = ['test_run_prep_command.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:task_test_base',
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
    'tests/python/pants_test:task_test_base',
  ],
)

python_tests(
  name = 'substitute_target_aliases_integration',
  sources = ['test_substitute_target_aliases_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
