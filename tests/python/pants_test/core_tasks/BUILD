# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'run_prep_command',
  sources = ['test_run_prep_command.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:task_test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)
