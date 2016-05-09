# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='cache_compile_integration',
  sources=['test_cache_compile_integration.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:zinc',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name='zinc_compile_integration',
  sources=['test_zinc_compile_integration.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name='java_compile_integration',
  sources=['test_java_compile_integration.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks/jvm_compile:zinc',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name='zinc_compile_jvm_platform_integration',
  sources=['test_zinc_compile_jvm_platform_integration.py'],
  dependencies = [
    ':jvm_platform_integration_mixin',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name='java_compile_settings_partitioning',
  sources=['test_java_compile_settings_partitioning.py'],
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks/jvm_compile:zinc',
    'src/python/pants/base:revision',
    'src/python/pants/util:memo',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_library(
  name='jvm_platform_integration_mixin',
  sources=['jvm_platform_integration_mixin.py'],
  dependencies = [
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
  ],
)
