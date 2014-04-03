# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(name = 'jvm-run-example-lib',
  dependencies = [],
  sources = ['JvmRunExample.scala']
)

jvm_binary(name ='jvm-run-example',
  main = 'com.pants.example.JvmRunExample',
  dependencies = [
    ':jvm-run-example-lib',
  ]
)
