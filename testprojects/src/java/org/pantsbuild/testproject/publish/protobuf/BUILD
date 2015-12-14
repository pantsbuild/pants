# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='protobuf-java',
  dependencies=[
    '3rdparty:protobuf-java',
    'testprojects/src/protobuf/org/pantsbuild/testproject/distance',
  ],
  sources=globs('*.java'),
  provides=artifact(
    org='org.pantsbuild.testproject.publish.protobuf',
    name='protobuf-java',
    repo=testing,
  )
)
