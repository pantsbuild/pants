# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='examplec',
  main='org.pantsbuild.duplicateres.examplec.Main',
  dependencies=[
    ':lib',
  ],
)

java_library(name='lib',
  sources=['Main.java'],
  resources=['testprojects/maven_layout/resource_collision/example_c/src/main/resources'],
  dependencies=[
    'testprojects/maven_layout/resource_collision/lib/src/main/java/org/pantsbuild/duplicateres/lib',
  ],
)
