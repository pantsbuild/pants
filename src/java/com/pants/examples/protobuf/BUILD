# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO(Eric Ayers): Invoking this target with goal 'bundle' doesn't actuall bundle its dependencies
# like its supposed to.
dependencies(name='protobuf',
  dependencies=[
    ':protobuf-example',
    ':protobuf-imports-example',
  ],
)

jvm_binary(name='protobuf-example',
  dependencies=[
    'src/protobuf/com/pants/examples/distance',
    '3rdparty:protobuf-java',
  ],
  source='ExampleProtobuf.java',
  main='com.pants.examples.protobuf.ExampleProtobuf',
)

jvm_binary(name='protobuf-imports-example',
  dependencies=[
    'src/protobuf/com/pants/examples/imports',
    '3rdparty:protobuf-java',
  ],
  source='imports/ExampleProtobufImports.java',
  main='com.pants.examples.protobuf.imports.ExampleProtobufImports',
)
