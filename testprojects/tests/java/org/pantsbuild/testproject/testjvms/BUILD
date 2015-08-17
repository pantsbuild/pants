# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(name='testjvms',
  dependencies=[
    ':six',
    ':seven',
    ':eight',
    ':eight-test-platform',
  ],
)

junit_tests(name='six',
  sources=['TestSix.java'],
  platform='java6',
  dependencies=[':base'],
)

junit_tests(name='seven',
  sources=['TestSeven.java'],
  platform='java7',
  dependencies=[':base'],
)

junit_tests(name='eight',
  sources=['TestEight.java'],
  platform='java8',
  dependencies=[':base'],
)

junit_tests(name='eight-test-platform',
  sources=['TestEight.java'],
  platform='java7',
  test_platform='java8',
  dependencies=[':base'],
)

java_library(name='base',
  sources=['TestBase.java'],
  dependencies=['3rdparty:junit'],
)