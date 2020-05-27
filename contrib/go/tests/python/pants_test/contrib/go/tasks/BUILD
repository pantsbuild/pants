# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources = ['*.py', '!*_integration.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'contrib/go/src/python/pants/contrib/go/targets',
    'contrib/go/src/python/pants/contrib/go/tasks',
    'contrib/go/src/python/pants/contrib/go:plugin',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
  timeout=120,
)


python_tests(
  name = 'integration',
  sources = ['*_integration.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'contrib/go:examples_directory',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:file_test_util',
    'src/python/pants/testutil:int-test',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=480,
)
