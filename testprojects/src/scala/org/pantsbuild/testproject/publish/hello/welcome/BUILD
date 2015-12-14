# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Seq-friendly wrapper for Java "greet" library: greet everything in a seq.

scala_library(name='welcome',
  dependencies=[
    'testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet:greet',
  ],
  sources=globs('*.scala'),
  provides = scala_artifact(org='org.pantsbuild.testproject.publish.hello',
                            name='welcome',
                            repo=testing,),
)
