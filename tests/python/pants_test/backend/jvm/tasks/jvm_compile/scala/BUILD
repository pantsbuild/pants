# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name='base_compile_integration_test',
  sources=['base_scalac_plugin_integration_test.py'],
  dependencies=[
    'examples/src/scala/org/pantsbuild/example:scalac_directory',
    'tests/python/pants_test/backend/jvm/tasks/jvm_compile:base_compile_integration_test',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='scalac_plugin_integration',
  sources=['test_scalac_plugin_integration.py'],
  dependencies=[
    ':base_compile_integration_test'
  ],
  timeout = 900,
  tags = {'integration', 'partially_type_checked'},
)
