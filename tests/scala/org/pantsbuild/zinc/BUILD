# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
  dependencies=[
    '3rdparty/jvm/org/scala-sbt:io',
    '3rdparty/jvm/org/scala-sbt:util-logging',
    '3rdparty/jvm/org/scala-sbt:zinc',
    '3rdparty:jsr305',
    '3rdparty:junit',
    '3rdparty:scalatest',
    'src/scala/org/pantsbuild/zinc',
    # TODO fix zinc unused deps false positives due to zinc not recording
    # dependencies of erased generic types: https://github.com/sbt/zinc/issues/147
    scoped('3rdparty:guava', scope='forced'),
    scoped('src/scala/org/pantsbuild/zinc/cache', scope='forced'),
  ],
  strict_deps=True,
)
