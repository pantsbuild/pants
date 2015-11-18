# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Tests functionality of protoc generating java code.

junit_tests(name='useproto',
  sources=['UseProtoTest.java',],
  dependencies=[
    '3rdparty:junit',
    '3rdparty:protobuf-java',
    'examples/src/protobuf/org/pantsbuild/example/distance',
  ],
)
