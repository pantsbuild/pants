# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Seq-friendly wrapper for Java "greet" library: greet everything in a seq.

scala_library(name='welcome',
  dependencies=[
    'examples/src/java/org/pantsbuild/example/hello/greet:greet',
  ],
  sources=globs('*.scala'),
  resources = [
    'examples/src/resources/org/pantsbuild/example/hello',
  ],
  provides = scala_artifact(org='org.pantsbuild.example.hello',
                            name='welcome',
                            repo=public,),
)
