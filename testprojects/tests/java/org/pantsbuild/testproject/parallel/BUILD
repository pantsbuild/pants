# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='parallel',
  sources=globs('ParallelTest*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
  concurrency='PARALLEL_CLASSES',
  threads=2,
)

# This target runs the same tests as the one above, but doesn't have the concurrency settings.
# Relies on the test.junit options being set as follows:
#   --test-junit-default-parallel --test-junit-parallel-threads=2
junit_tests(name='cmdline',
  sources=globs('ParallelTest*.java'),
  dependencies=[
    '3rdparty:junit',
  ],
)

# These tests are annotated with @TestParallel so should be able to run
# in parallel even when --test-junit-default-concurrency=SERIAL is set.
junit_tests(name='annotated-parallel',
  sources=globs('AnnotatedParallelTest*.java'),
  dependencies=[
    '3rdparty:junit',
    ':junit-runner-annotations'
  ],
  threads=2,
)

# Even though these tests are run with 'parallel_classes' concurrency, they are annotated
# with @TestSerial, so they should run serially, even when even when
# --test-junit-default-concurrency={PARALLEL_CLASSES, PARALLEL_METHODS, PARALLEL_CLASSES_AND_METHODS} is set
# See: https://github.com/pantsbuild/pants/issues/3209
junit_tests(name='annotated-serial',
  sources=globs('AnnotatedSerialTest*.java'),
  dependencies=[
    '3rdparty:junit',
    ':junit-runner-annotations'
  ],
  concurrency='PARALLEL_CLASSES',
  threads=2,
)

jar_library(
  name='junit-runner-annotations',
  jars=[
    jar(org='org.pantsbuild', name='junit-runner-annotations', rev='0.0.11'),
  ],
)
