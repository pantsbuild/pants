# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'compile_context',
  sources = ['test_compile_context.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks/jvm_compile:compile_context',
    'tests/python/pants_test:base_test',
  ],
)

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

python_tests(
  name = 'jvm_compile',
  sources = ['test_jvm_compile.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks/jvm_compile',
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

python_tests(
  name='dep_exports_integration',
  sources=['test_dep_exports_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=600,
)

python_tests(
  name='missing_dependency_finder',
  sources=['test_missing_dependency_finder.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile:missing_dependency_finder',
  ],
)

python_tests(
  name='missing_dependency_finder_integration',
  sources=['test_missing_dependency_finder_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
    'src/python/pants/backend/jvm/tasks/jvm_compile:missing_dependency_finder',
  ],
  tags={'integration'},
)
