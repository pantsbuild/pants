# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Test the Hello World example's "greet" library

junit_tests(name='greet',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:junit',
    'examples/src/java/com/pants/examples/hello/greet',
  ],
  resources=[
    'examples/src/resources/com/pants/examples/hello',
  ],
)
