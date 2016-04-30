# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This doesn't test much. It shows Pants-ly using Thrift from Java, though.

junit_tests(name='usethrift',
  sources=['UseThriftTest.java',],
  dependencies=[
    '3rdparty:junit',
    '3rdparty:thrift-0.9.2',
    'examples/src/thrift/org/pantsbuild/example/distance:distance-java',
    'examples/src/thrift/org/pantsbuild/example/precipitation:precipitation-java',
  ],
)


