# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(name = 'jvm-run-example-lib',
  dependencies = [],
  sources = ['JvmRunExample.scala'],
  java_sources = [pants('src/java/com/pants/examples/hello/greet:greet')],
  provides=artifact(org='com.pants.common.example',
                    name='scala_lib',
                    repo = 'build-support/ivy:public',),
)

jvm_binary(name ='jvm-run-example',
  main = 'com.pants.example.JvmRunExample',
  dependencies = [
    ':jvm-run-example-lib',
  ]
)
