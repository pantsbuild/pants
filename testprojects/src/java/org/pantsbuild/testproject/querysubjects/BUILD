# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='my-java-file',
  sources=[
    'MyJavaFile.java',
  ],
)

java_library(name='another-file',
  sources=[
    'AnotherFile.java',
  ],
  dependencies=[
    ':my-java-file',
  ],
)

java_library(name='untested-file',
  sources=[
    'UntestedFile.java',
  ],
)

target(name='untested-target')
