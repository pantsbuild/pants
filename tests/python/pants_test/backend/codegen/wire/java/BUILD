# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  sources = globs('*.py', exclude=[globs('*_integration.py')]),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/codegen/wire/java',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:revision',
    'src/python/pants/base:validation',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)


python_tests(
  name = 'integration',
  sources = globs('*_integration.py'),
  dependencies = [
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
