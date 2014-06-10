# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_protobuf_library(name='imports',
  sources=['test_imports.proto',],
  imports=[':protobuf-test-import',],
)

# Normally, this would live in 3rdparty. This is here because we didn't want to clutter Pants' own
# 3rdparty with its sample code's deps. Note that this could also be done by simply including
# jar(org=..., name=..., rev=...) directly in the imports list.
jar_library(name='protobuf-test-import',
  jars = [
    jar(org='com.squareup.testing.protolib', name='protolib-test', rev='1.0'),
  ],
)