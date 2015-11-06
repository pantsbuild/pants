# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='cucumber',
  sources=['CukeTest.java'],
  dependencies=[
    ':lib',
  ],
)

java_library(name='lib',
  sources=[
    'DemoSteps.java',
  ],
  dependencies=[
    '3rdparty:junit',
    'testprojects/3rdparty/cucumber:cuke-core',
    'testprojects/3rdparty/cucumber:cuke-guice',
    'testprojects/3rdparty/cucumber:cuke-java',
    'testprojects/3rdparty/cucumber:cuke-junit',
    'testprojects/3rdparty/cucumber:com.google.inject.guice',
    'testprojects/tests/resources/org/pantsbuild/testproject/cucumber',
  ],
)
