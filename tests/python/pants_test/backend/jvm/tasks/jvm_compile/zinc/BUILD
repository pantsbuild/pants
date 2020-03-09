# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'zinc_compile_integration_base',
  sources = ['zinc_compile_integration_base.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:scalac_directory',
    'testprojects/src/java/org/pantsbuild/testproject:annotation_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:compilation_failure_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:compilation_warnings_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:emptyscala_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:exclude_direct_dep_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:javasources_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:sharedsources_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:unicode_directory',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='zinc_compile_integration_with_zjars',
  sources=['test_zinc_compile_integration_with_zjars.py'],
  dependencies=[
    ':zinc_compile_integration_base',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
  ],
  timeout = 1200,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name='zinc_compile_integration',
  sources=['test_zinc_compile_integration.py'],
  dependencies=[
    ':zinc_compile_integration_base',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  timeout = 1200,
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name='zinc_compile',
  sources=['test_zinc_compile.py'],
  dependencies=[
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'src/python/pants/testutil/jvm:jvm_tool_task_test_base',
  ]
)
