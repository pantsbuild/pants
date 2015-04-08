# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
  name='examplec',
  sources=['ExampleCTest.java'],
  dependencies=[
    '3rdparty:junit',
    'testprojects/maven_layout/resource_collision/example_c/src/main/java/org/pantsbuild/duplicateres/examplec:lib',
    'testprojects/maven_layout/resource_collision/lib/src/main/java/org/pantsbuild/duplicateres/lib',
  ],
)
