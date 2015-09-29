# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(name = 'jvm-run-example-lib',
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject/publish/hello/welcome',
  ],
  sources = ['JvmRunExample.scala'],
  provides = scala_artifact(org='org.pantsbuild.testproject.publish',
                            name='jvm-example-lib',
                            repo=testing,)
)
