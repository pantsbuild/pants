# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
  name='protobuf-2.4.1',
  jars = [
    jar(org='com.google.protobuf', name='protobuf-java', rev='2.4.1').with_sources(),
  ],
)

jar_library(
  name = 'protobuf-java',
  dependencies = [
    ':protobuf-2.4.1',
  ],
)
