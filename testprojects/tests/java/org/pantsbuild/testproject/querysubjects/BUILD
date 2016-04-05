# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_tests(name='my-java-file',
  sources=[
    'TestMyJavaFile.java',
  ],
  dependencies=[
    'testprojects/src/java/org/pantsbuild/testproject/querysubjects:my-java-file',
    '3rdparty:junit',
  ],
)

java_tests(name='another-file',
  sources=[
    'TestAnotherFile.java',
  ],
  dependencies=[
    'testprojects/src/java/org/pantsbuild/testproject/querysubjects:another-file',
    '3rdparty:junit',
  ],
)
