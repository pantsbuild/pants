# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Seq-friendly wrapper for Java "greet" library: greet everything in a seq.

scala_library(name='welcome',
  dependencies=[
    'examples/src/java/com/pants/examples/hello/greet:greet',
  ],
  sources=globs('*.scala'),
  resources = [
    'examples/src/resources/com/pants/examples/hello',
  ],
  provides = artifact(org='com.pants.examples.hello',
                      name='welcome',
                      repo=public,),
)
