# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
    name='resolve_requirements',
    sources=['test_resolve_requirements.py'],
    dependencies=[
      '3rdparty/python:pex',
      'src/python/pants/backend/python:python_requirement',
      'src/python/pants/backend/python/targets',
      'src/python/pants/backend/python/tasks2',
      'src/python/pants/base:build_root',
      'src/python/pants/util:contextutil',
      'tests/python/pants_test/tasks:task_test_base',
    ]
)

python_tests(
    name='select_interpreter',
    sources=['test_select_interpreter.py'],
    dependencies=[
      '3rdparty/python:mock',
      '3rdparty/python:pex',
      'src/python/pants/backend/python:interpreter_cache',
      'src/python/pants/backend/python:python_setup',
      'src/python/pants/backend/python/targets',
      'src/python/pants/backend/python/tasks2',
      'src/python/pants/base:exceptions',
      'tests/python/pants_test/tasks:task_test_base',
    ]
)
