# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


junit_tests(
  sources=['MatcherTest.java'],
  dependencies=[
    '3rdparty:junit',
    '3rdparty/jvm/org/hamcrest:hamcrest-library',
    ':avro'
  ],
)


jar_library(name='avro',
            jars=[
              jar('org.apache.avro', 'avro', '1.7.4')
            ])
