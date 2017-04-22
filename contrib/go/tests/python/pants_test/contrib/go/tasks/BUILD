# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources = globs('*.py', exclude=[globs('*_integration.py')]),
  dependencies=[
    'contrib/go/src/python/pants/contrib/go:plugin',
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'contrib/go/src/python/pants/contrib/go/targets',
    'contrib/go/src/python/pants/contrib/go/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)


python_tests(
  name = 'integration',
  sources = globs('*_integration.py'),
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/testutils:file_test_util',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=180,
)
