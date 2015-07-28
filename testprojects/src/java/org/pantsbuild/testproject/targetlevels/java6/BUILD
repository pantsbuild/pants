# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='java6',
  main='org.pantsbuild.testproject.targetlevels.java6.Six',
  platform='java6',
  dependencies=[':lib'],
)

java_library(name='lib',
  sources=globs('*.java'),
  platform='java6',
)