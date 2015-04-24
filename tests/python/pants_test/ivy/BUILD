# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'ivy',
  dependencies = [
    ':bootstrapper',
    ':ivy_subsystem',
  ],
)

python_tests(
  name='bootstrapper',
  sources = [ 'test_bootstrapper.py' ],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:ivy_resolve',
    'src/python/pants/ivy',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)

python_tests(
  name='ivy_subsystem',
  sources = [ 'test_ivy_subsystem.py' ],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:ivy_resolve',
    'src/python/pants/ivy',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ]
)
