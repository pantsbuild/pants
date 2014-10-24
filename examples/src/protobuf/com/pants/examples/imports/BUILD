# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_protobuf_library(name='imports',
  sources=['test_imports.proto',],
  imports=[
    'examples/3rdparty:protobuf-test-import',
    ':jars',
  ],
)

jar_library(name='jars',
  dependencies=[
    'examples/src/protobuf/com/pants/examples/imports',
  ]
)
