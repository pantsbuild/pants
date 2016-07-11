# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_protobuf_library(name='unpacked_jars',
  # This uses the legacy deferred sources mechanism.
  sources=from_target(':external-source'),
)

remote_sources(name='better-unpacked-jars',
  # This uses the new deferred sources mechanism.
  dest=java_protobuf_library,
  sources_target=':external-source',
)

unpacked_jars(name='external-source',
  libraries=[':external-source-jars'],
  include_patterns=[
    'com/squareup/testing/**/*.proto',
  ],
)

jar_library(name='external-source-jars',
  jars=[
    jar(org='com.squareup.testing.protolib', name='protolib-external-test', rev='0.0.2'),
  ],
)
