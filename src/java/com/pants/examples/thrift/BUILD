# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Created to test the functionality of Thrift code generation,
# using the distance example

jvm_binary(name='thrift',
  dependencies=[
    'src/thrift/com/pants/examples/distance:distance-java',
  ],
  source='ExampleThrift.java',
  main='com.pants.examples.thrift.ExampleThrift',
)