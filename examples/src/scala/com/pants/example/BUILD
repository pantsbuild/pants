# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(name = 'jvm-run-example-lib',
  dependencies = [
    'examples/src/scala/com/pants/example/hello/welcome',
  ],
  sources = ['JvmRunExample.scala'],
  provides = artifact(org='com.pants.example',
                      name='jvm-example-lib',
                      repo='build-support/ivy:public',)
)

jvm_binary(name ='jvm-run-example',
  main = 'com.pants.example.JvmRunExample',
  dependencies = [
    ':jvm-run-example-lib',
  ]
)
