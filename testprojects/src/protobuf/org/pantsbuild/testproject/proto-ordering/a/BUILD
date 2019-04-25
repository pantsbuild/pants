# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

remote_sources(
  dest=java_protobuf_library,
  sources_target=':sources',
)

unpacked_jars(
  name='sources',
  libraries=[
    '3rdparty:protobuf-test-import',
  ],
  include_patterns=[
    '**/*.proto',
  ],
)
