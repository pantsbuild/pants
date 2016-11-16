# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_tests(
  name='junit',
  dependencies=[
    '3rdparty:guava',
    '3rdparty:junit',
    '3rdparty/jvm/commons-io',
    '3rdparty/jvm/org/hamcrest:hamcrest-core',
    '3rdparty/jvm/org/hamcrest:hamcrest-library',
    'src/java/org/pantsbuild/junit/annotations',
    'src/java/org/pantsbuild/tools/junit',
    'tests/java/org/pantsbuild/tools/junit/lib:test-dep',
    'tests/scala/org/pantsbuild/tools/junit/lib:scala-test-dep',
  ],
  sources=globs('*Test.java'),
  timeout=180,
)
