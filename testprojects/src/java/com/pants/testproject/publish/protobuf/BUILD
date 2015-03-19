# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='protobuf-java',
  dependencies=[
    'testprojects/src/protobuf/com/pants/testproject/distance',
  ],
  sources= globs('*.java'),
  provides = artifact(
    org = 'com.pants.testproject.publish.protobuf',
    name = 'protobuf-java',
    repo = public,
  )
)

