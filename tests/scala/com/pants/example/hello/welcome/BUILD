# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# The welcome library doesn't do much, but let's test it anyhow.

junit_tests(name='welcome',
  dependencies=[
    'src/scala/com/pants/example/hello/welcome:welcome',
    '3rdparty/jvm/junit',
    '3rdparty/jvm/specs',
  ],
  sources=globs('*.scala'),
)
