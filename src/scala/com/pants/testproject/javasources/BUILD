# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
  name = 'javasources',
  java_sources=[
    pants('src/java/com/pants/testproject/javasources'),
    pants('src/java/com/pants/examples/hello/greet:greet')
  ],
  sources = rglobs('*.scala')
)
