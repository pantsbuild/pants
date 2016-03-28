# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_tests(name='tests',
  sources=['AllTests.java'],
  dependencies=[
    '3rdparty:junit',
    ':check',
    ':lib',
  ],
)

jvm_binary(name='bin',
  source='CheckForLibrary.java',
  main='org.pantsbuild.testproject.junit.testscope.CheckForLibrary',
  dependencies=[
    ':lib',
  ],
)

java_library(name='check',
  sources=['CheckForLibrary.java'],
)

java_library(name='lib',
  sources=['SomeLibraryFile.java'],
  scope='test',
)
