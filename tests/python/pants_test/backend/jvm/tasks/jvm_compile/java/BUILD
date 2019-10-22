# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='cache_compile_integration',
  sources=['test_cache_compile_integration.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile/zinc',
    'src/python/pants/base:build_environment',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  tags = {'integration'},
  timeout=720,
)

python_tests(
  name='zinc_compile_integration',
  sources=['test_zinc_compile_integration.py'],
  dependencies=[
    'src/python/pants/build_graph',
    'tests/python/pants_test/backend/jvm/tasks:missing_jvm_check',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/scala/org/pantsbuild/example:hello_directory',
    'testprojects/3rdparty:javactool_directory',
    'testprojects/src/java/org/pantsbuild/testproject:bench_directory',
    'testprojects/src/java/org/pantsbuild/testproject:compilation_warnings_directory',
    'testprojects/src/java/org/pantsbuild/testproject:dummies_directory',
    'testprojects/src/java/org/pantsbuild/testproject:phrases_directory',
    'testprojects/src/java/org/pantsbuild/testproject:printversion_directory',
    'testprojects/src/scala/org/pantsbuild/testproject:unicode_directory',
  ],
  tags = {'integration'},
  timeout=600,
)

python_tests(
  name='java_compile_integration',
  sources=['test_java_compile_integration.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile/zinc',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
    'tests/python/pants_test/cache:cache_server',
    'testprojects/src/java/org/pantsbuild/testproject:annotation_directory',
    'testprojects/src/java/org/pantsbuild/testproject:jarversionincompatibility_directory',
    'testprojects/src/java/org/pantsbuild/testproject:nocache_directory',
    'testprojects/src/java/org/pantsbuild/testproject:publish_directory',
    'testprojects/src/java/org/pantsbuild/testproject:resdependency_directory',
    'testprojects/src/java/org/pantsbuild/testproject:unicode_directory',
    'testprojects/tests/java/org/pantsbuild/testproject:matcher_directory',
  ],
  tags = {'integration'},
  timeout=600,
)

python_tests(
  name='javac_plugin_integration',
  sources=['test_javac_plugin_integration.py'],
  dependencies=[
    'tests/python/pants_test/backend/jvm/tasks:missing_jvm_check',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
    'examples/src/java/org/pantsbuild/example:javac_directory',
  ],
  timeout = 360,
  tags = {'integration'},
)

python_tests(
  name = 'java_compile_settings_partitioning',
  sources = ['test_java_compile_settings_partitioning.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile/zinc',
    'src/python/pants/fs',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/java/distribution',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

python_library(
  name = 'jvm_platform_integration_mixin',
  sources = ['jvm_platform_integration_mixin.py'],
  dependencies = [
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
)
