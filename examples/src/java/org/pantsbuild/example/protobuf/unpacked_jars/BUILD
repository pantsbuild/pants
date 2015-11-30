# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='unpacked_jars',
  basename='protobuf-unpacked-jars-example',
  source='ExampleProtobufExternalArchive.java',
  main='org.pantsbuild.example.protobuf.unpacked_jars.ExampleProtobufExternalArchive',
  dependencies=[
    '3rdparty:protobuf-java',
    'examples/src/protobuf/org/pantsbuild/example/unpacked_jars',
  ],
)
