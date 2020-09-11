# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources = ['*.py', '!*_integration.py'],
  dependencies = [
    'src/python/pants/backend/codegen/protobuf/java',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:ordered_set',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)


python_tests(
  name = 'integration',
  sources = ['*_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:protobuf_directory',
    'testprojects/src/java/org/pantsbuild/testproject:proto-ordering_directory',
    'testprojects/src/protobuf/org/pantsbuild/testproject:import_from_buildroot_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 800,
)
