# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='base',
  sources=['TestBase.java'],
  platform='java7',
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
  name='eight-runtime-platform',
  sources=['TestEight.java'],
  platform='java7',
  runtime_platform='java8',
  dependencies=[':base'],
  strict_deps=False,
)
