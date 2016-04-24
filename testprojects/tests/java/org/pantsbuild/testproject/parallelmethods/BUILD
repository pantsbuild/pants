# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='parallelmethods',
  sources=globs('ParallelMethodsDefaultParallel*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
  concurrency='PARALLEL_BOTH',
  threads=4,
)

# This target runs the same tests as the one above, but doesn't have the concurrency settings.
# Relies on the test.junit options being set as follows:
#   --test-junit-default-concurrency=PARALLEL_BOTH --test-junit-parallel-threads=4
junit_tests(name='cmdline',
  sources=globs('ParallelMethodsDefaultParallel*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
)
