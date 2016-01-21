# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'jvm_classpath_published',
  sources = ['test_jvm_classpath_published.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/jvm/tasks/jvm_compile:jvm_classpath_publisher',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_library(
  name='base_compile_integration_test',
  sources=['base_compile_integration_test.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
)

python_tests(
  name='declared_deps_integration',
  sources=['test_declared_deps_integration.py'],
  dependencies=[
    ':base_compile_integration_test',
  ],
  tags={'integration'},
)
