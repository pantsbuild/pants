# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='shadingdep',
  main='org.pantsbuild.testproject.shadingdep.Dependency',
  basename='shadingdep',
  dependencies=[
    ':lib',
    'testprojects/src/java/org/pantsbuild/testproject/shadingdep/subpackage',
  ],
)

jvm_binary(name='other',
  main='org.pantsbuild.testproject.shadingdep.otherpackage.ShadeWithTargetId',
  basename='other',
  dependencies=[
    'testprojects/src/java/org/pantsbuild/testproject/shadingdep/otherpackage',
  ],
)

java_library(name='lib',
  sources=globs('*.java'),
)
