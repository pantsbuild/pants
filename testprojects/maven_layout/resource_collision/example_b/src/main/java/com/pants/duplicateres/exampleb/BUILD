# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='exampleb',
  main='com.pants.duplicateres.exampleb.Main',
  dependencies=[':lib'],
)

java_library(name='lib',
  sources=['Main.java'],
  resources=['testprojects/maven_layout/resource_collision/example_b/src/main/resources'],
  dependencies=[
    'testprojects/maven_layout/resource_collision/example_c/src/main/java/com/pants/duplicateres/examplec:lib',
    'testprojects/maven_layout/resource_collision/lib/src/main/java/com/pants/duplicateres/lib',
  ],
)
