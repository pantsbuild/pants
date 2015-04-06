# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(name = 'jvm-run-example-lib',
  dependencies = [
    'examples/src/scala/com/pants/examples/hello/welcome',
  ],
  sources = ['JvmRunExample.scala'],
  provides = artifact(org='com.pants.examples',
                      name='jvm-example-lib',
                      repo=public,)
)

jvm_binary(name ='jvm-run-example',
  main = 'com.pants.examples.JvmRunExample',
  dependencies = [
    ':jvm-run-example-lib',
  ]
)

page(
  name='readme',
  source='readme.md',
  links=[
    'examples/src/java/com/pants/examples:readme',
  ],
)
