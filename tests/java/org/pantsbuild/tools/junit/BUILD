# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

CONSOLE_OUTPUT_TEST =  ['impl/ConsoleRunnerConsoleOutputTest.java']
JUNIT_TEST_LIB = ['impl/ConsoleRunnerTestHelper.java',
                  'impl/TestRegistry.java']

java_library(
  name='junit-test-dep',
  dependencies=[
      '3rdparty:junit',
      '3rdparty/jvm/commons-io',
      'src/java/org/pantsbuild/junit/annotations',
      'src/java/org/pantsbuild/tools/junit',
    ],
   sources=JUNIT_TEST_LIB
)

java_tests(
  name='junit',
  dependencies=[
    ':junit-test-dep',
  ],
  sources=globs('impl/*.java', exclude=[CONSOLE_OUTPUT_TEST, JUNIT_TEST_LIB])
)

java_tests(
  name='junit-console-runner',
  dependencies=[
    ':junit-test-dep',
  ],
  sources=CONSOLE_OUTPUT_TEST
)
