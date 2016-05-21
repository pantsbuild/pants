# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(name = 'jvm-run-example-lib',
  dependencies = [
    'examples/src/scala/org/pantsbuild/example/hello/welcome',
  ],
  sources = ['JvmRunExample.scala'],
  provides = scala_artifact(org='org.pantsbuild.example',
                            name='jvm-example-lib',
                            repo=public,)
)

jvm_binary(name ='jvm-run-example',
  main = 'org.pantsbuild.example.JvmRunExample',
  dependencies = [
    ':jvm-run-example-lib',
  ]
)

page(
  name='readme',
  source='README.md',
  links=[
    'examples/src/java/org/pantsbuild/example:readme',
  ],
)
