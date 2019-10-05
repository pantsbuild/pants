# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name="testprojects_integration",
  sources=['test_testprojects_integration.py'],
  dependencies=[
    'examples/src/antlr/org/pantsbuild/example:all_directories',
    'examples/src/java/org/pantsbuild/example:all_directories',
    'examples/src/protobuf/org/pantsbuild/example:all_directories',
    'examples/src/python/example:all_directories',
    'examples/src/scala/org/pantsbuild/example:all_directories',
    'examples/src/thrift/org/pantsbuild/example:all_directories',
    'examples/src/wire/org/pantsbuild/example:all_directories',
    'examples/tests/java/org/pantsbuild/example:all_directories',
    'examples/tests/python/example_test:all_directories',
    'examples/tests/scala/org/pantsbuild/example:all_directories',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test:test_base',
    'testprojects/maven_layout:all_directories',
    'testprojects/src/antlr/python:all_directories',
    'testprojects/src/java/org/pantsbuild/testproject:all_directories',
    'testprojects/src/protobuf/org/pantsbuild/testproject:all_directories',
    'testprojects/src/python:all_directories',
    'testprojects/src/scala/org/pantsbuild/testproject:all_directories',
    'testprojects/src/thrift/org/pantsbuild:all_directories',
    'testprojects/tests/java/org/pantsbuild:all_directories',
    'testprojects/tests/python:all_directories',
    'testprojects/tests/scala/org/pantsbuild/testproject:all_directories',
  ],
  tags = {'integration'},
  timeout=950,
)
