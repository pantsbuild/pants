# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='ivyclassifier',
  sources=['IvyClassifierTest.java'],
  resources=[
    'testprojects/tests/resources/org/pantsbuild/testproject/ivyclassifier',
  ],
  dependencies=[
   '3rdparty:junit',
   ':jars_with_classifier',
  ],
)

jar_library(name='jars_with_classifier',
  jars = [
    jar(org='org.apache.avro', name='avro', rev='1.7.7'),
    jar(org='org.apache.avro', name='avro', rev='1.7.7', classifier='tests'),
  ]
)
