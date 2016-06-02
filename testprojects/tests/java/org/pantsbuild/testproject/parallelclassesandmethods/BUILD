# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='parallelclassesandmethods',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
  concurrency='PARALLEL_CLASSES_AND_METHODS',
  threads=4,
)

# This target runs the same tests as the one above, but doesn't have the concurrency settings.
# Relies on the test.junit options being set as follows:
#   --test-junit-default-concurrency=PARALLEL_CLASSES_AND_METHODS --test-junit-parallel-threads=4
junit_tests(name='cmdline',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
)
