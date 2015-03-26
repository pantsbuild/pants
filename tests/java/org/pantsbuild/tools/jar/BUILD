# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
  name='jar',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:commons-io',
    '3rdparty:guava',
    '3rdparty:guava-testlib',
    '3rdparty:junit',
    'src/java/org/pantsbuild/tools/jar',
  ],
  resources=[
    'tests/resources/org/pantsbuild/tool/jar',
  ],
)
