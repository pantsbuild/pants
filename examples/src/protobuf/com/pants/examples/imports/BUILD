# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_protobuf_library(name='imports',
  sources=['test_imports.proto',],
  imports=[
    '3rdparty:protobuf-test-import',
    jar(org='com.squareup.testing.protolib', name='protolib-test', rev='1.0.1'),
  ],
)
