# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='main-class',
  dependencies=[
    ':dependent-class',
  ],
  sources=['MainClass.java']
)

java_library(
  name='dependent-class',
  dependencies=[],
  sources=['DependentClass.java']
)

jvm_binary(
  name='pants-runner-testproject',
  dependencies=[
    ':main-class',
  ]
)
