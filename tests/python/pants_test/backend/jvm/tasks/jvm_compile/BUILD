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
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'jvm_compile',
  sources = ['test_jvm_compile.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)


python_library(
  name='base_compile_integration_test',
  sources=['base_compile_integration_test.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='declared_deps_integration',
  sources=['test_declared_deps_integration.py'],
  dependencies=[
    ':base_compile_integration_test',
    'testprojects/src/java/org/pantsbuild/testproject:missingdirectdepswhitelist_directory',
    'testprojects/src/java/org/pantsbuild/testproject:missingjardepswhitelist_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=900,
)

python_tests(
  name='dep_exports_integration',
  sources=['test_dep_exports_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/testutil:int-test',
    'testprojects/tests/java/org/pantsbuild/testproject:exports_directory',
    'testprojects/tests/scala/org/pantsbuild/testproject:exports_directory',
    'testprojects/tests/scala/org/pantsbuild/testproject:non_exports_directory',
    'testprojects/src/thrift/org/pantsbuild:thrift_exports_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=920,
)

python_tests(
  name = 'missing_dependency_finder',
  sources = ['test_missing_dependency_finder.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:missing_dependency_finder',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='missing_dependency_finder_integration',
  sources=['test_missing_dependency_finder_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'src/python/pants/backend/jvm/tasks/jvm_compile:missing_dependency_finder',
    'testprojects/src/java/org/pantsbuild/testproject:dummies_directory',
    'testprojects/src/java/org/pantsbuild/testproject:missingjardepswhitelist_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout = 500,
)
