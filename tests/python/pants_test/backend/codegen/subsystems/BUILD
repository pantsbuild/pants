# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='thrift_defaults',
  sources=['test_thrift_defaults.py'],
  dependencies = [
    'src/python/pants/backend/codegen/subsystems:thrift_defaults',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/build_graph',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:base_test',
  ],
)
