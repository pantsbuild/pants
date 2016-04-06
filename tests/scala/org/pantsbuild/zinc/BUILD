# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='zinc',
  dependencies=[
    '3rdparty/jvm/org/scala-sbt:incrementalcompiler',
    '3rdparty/jvm/org/scala-sbt:io',
    '3rdparty:guava',
    '3rdparty:jsr305',
    '3rdparty:junit',
    '3rdparty:scalatest',
    'src/scala/org/pantsbuild/zinc',
    'src/scala/org/pantsbuild/zinc/cache',
  ],
  sources=globs('*.scala'),
  strict_deps=True,
)
