# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
  name='jar',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:args4j',
    '3rdparty:easymock',
    '3rdparty:guava',
    '3rdparty:guava-testlib',
    '3rdparty:junit',
    'src/java/org/pantsbuild/args4j',
    'src/java/org/pantsbuild/testing',
    'src/java/org/pantsbuild/tools/jar',
  ],
  resources=[
    'tests/resources/org/pantsbuild/tools/jar',
  ],
)
