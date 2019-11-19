# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='base',
  sources=['TestBase.java'],
  dependencies=['3rdparty:junit'],
)


junit_tests(
  name='eight',
  sources=['TestEight.java'],
  platform='java8',
  dependencies=[':base'],
  strict_deps=False,
)

junit_tests(
  name='eight-test-platform',
  sources=['TestEight.java'],
  platform='java7',
  test_platform='java8',
  dependencies=[':base'],
  strict_deps=False,
)
