# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Local sources which depend on remote sources extracted from a jar.
java_protobuf_library(
  sources=['*.proto'],
  dependencies=[
    ':remote',
  ],
)

remote_sources(
  name='remote',
  dest=java_protobuf_library,
  sources_target=':unpacked',
)

unpacked_jars(
  name='unpacked',
  libraries=[
    '3rdparty:protobuf-test-import',
  ],
  include_patterns=[
    '**/*.proto',
  ],
)
