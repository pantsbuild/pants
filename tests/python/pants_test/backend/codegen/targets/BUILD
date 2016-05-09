# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'java_protobuf_library',
  sources = ['test_java_protobuf_library.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'java_wire_library',
  sources = ['test_java_wire_library.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'java_antlr_library',
  sources = ['test_java_antlr_library.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ],
)
