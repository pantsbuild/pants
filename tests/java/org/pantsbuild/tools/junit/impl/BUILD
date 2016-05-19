# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_tests(
  name='junit',
  dependencies=[
    ':test-base',
    'tests/java/org/pantsbuild/tools/junit/lib:test-dep',
  ],
  sources=globs('*Test.java'),
  strict_deps=False,
  timeout=180,
)

java_library(
  name='test-base',
  sources=['ConsoleRunnerTestBase.java'],
  dependencies = [
    'src/java/org/pantsbuild/junit/annotations',
    'src/java/org/pantsbuild/tools/junit',
    'tests/java/org/pantsbuild/tools/junit/lib:test-dep',
    '3rdparty:guava',
    '3rdparty:junit',
  ],
)
