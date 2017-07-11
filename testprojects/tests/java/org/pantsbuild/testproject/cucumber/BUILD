# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
  sources=[
    'BadnamesTest.java',
    'CukeTest.java',
    'NormalTest.java',
  ],
  dependencies=[
    '3rdparty:junit',
    ':lib',
    'testprojects/3rdparty/cucumber:cuke-core',
    'testprojects/3rdparty/cucumber:cuke-junit',
  ],
)

java_library(name='lib',
  sources=[
    'BadnamesSteps.java',
    'DemoSteps.java',
  ],
  dependencies=[
    '3rdparty:junit',
    'testprojects/3rdparty/cucumber:cuke-guice',
    'testprojects/3rdparty/cucumber:cuke-java',
    'testprojects/tests/resources/org/pantsbuild/testproject/cucumber',
  ],
)
