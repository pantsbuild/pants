# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='zinc',
  dependencies=[
    '3rdparty/jvm/org/scala-sbt:io',
    '3rdparty/jvm/org/scala-sbt:util-logging',
    '3rdparty/jvm/org/scala-sbt:zinc',
    scoped('3rdparty:guava', scope='forced'),
    '3rdparty:jsr305',
    '3rdparty:junit',
    '3rdparty:scalatest',
    'src/scala/org/pantsbuild/zinc',
    scoped('src/scala/org/pantsbuild/zinc/cache', scope='forced'),
  ],
  sources=globs('*.scala'),
  strict_deps=True,
)
