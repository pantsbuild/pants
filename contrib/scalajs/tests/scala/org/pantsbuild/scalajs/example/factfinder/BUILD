# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='factfinder',
  dependencies=[
    '3rdparty:guava',
    '3rdparty:junit',
    '3rdparty:scalatest',
    'contrib/scalajs/3rdparty/jvm/org/mozilla:rhino',
    'contrib/scalajs/examples/src/scala/org/pantsbuild/scalajs/example/factfinder',
    'examples/src/scala/org/pantsbuild/example/fact:fact-js',
  ],
  sources=globs('*.scala'),
)
