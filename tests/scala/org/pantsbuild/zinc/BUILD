# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='zinc',
  dependencies=[
    '3rdparty/jvm/com/typesafe/sbt:incremental-compiler',
    '3rdparty:junit',
    '3rdparty:scalatest',
    'src/scala/org/pantsbuild/zinc',
    # TODO fix zinc unused deps false positives
    scoped('3rdparty:guava', scope='forced'),
    scoped('src/scala/org/pantsbuild/zinc/cache', scope='forced'),
  ],
  sources=globs('*.scala'),
  strict_deps=True,
)
