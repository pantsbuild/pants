# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  sources = ['*.py', '!*_integration.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:parameterized',
    'src/python/pants/backend/codegen/wire/java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:revision',
    'src/python/pants/base:validation',
    'src/python/pants/build_graph',
    'src/python/pants/java/jar',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)


python_tests(
  name = 'integration',
  sources = ['*_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'src/python/pants/testutil:file_test_util',
    'examples/src/java/org/pantsbuild/example:wire_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 300,
)
