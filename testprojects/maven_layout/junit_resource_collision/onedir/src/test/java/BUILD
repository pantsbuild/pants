# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(name='java',
  sources=[
    'org/pantsbuild/duplicates/FirstTest.java'
  ],
  dependencies=[
    '3rdparty:junit',
  ],
  resources=[
    'testprojects/maven_layout/junit_resource_collision/onedir/src/test/resources'
  ],
  cwd='testprojects/maven_layout/junit_resource_collision/onedir',
)