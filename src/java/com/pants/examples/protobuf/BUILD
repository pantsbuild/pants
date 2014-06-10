# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='protobuf-all',
  dependencies=[
    ':protobuf',
    ':protobuf-imports',
  ],
)

jvm_binary(name='protobuf',
  dependencies=[
    'src/protobuf/com/pants/examples/distance',
  ],
  source='ExampleProtobuf.java',
  main='com.pants.examples.protobuf.ExampleProtobuf',
)

jvm_binary(name='protobuf-imports',
  dependencies=[
    'src/protobuf/com/pants/examples/imports',
  ],
  source='imports/ExampleProtobufImports.java',
  main='com.pants.examples.protobuf.ExampleProtobufImports',
)