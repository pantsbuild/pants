# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# The welcome library doesn't do much, but let's test it anyhow.

junit_tests(name='welcome',
  dependencies=[
    'examples/src/scala/com/pants/example/hello/welcome:welcome',
    '3rdparty:junit',
    '3rdparty:specs',
  ],
  sources=globs('*.scala'),
)
