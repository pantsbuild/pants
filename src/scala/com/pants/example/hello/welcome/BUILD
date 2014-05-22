# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Seq-friendly wrapper for Java "greet" library: greet everything in a seq.

scala_library(name='welcome',
  dependencies=[
    pants('src/java/com/pants/examples/hello/greet:greet'),
  ],
  sources=globs('*.scala'),
  resources = [
    'src/resources/com/pants/example/hello',
  ],
)
