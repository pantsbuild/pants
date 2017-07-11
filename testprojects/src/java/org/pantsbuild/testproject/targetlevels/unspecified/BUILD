# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
  main='org.pantsbuild.testproject.targetlevels.unspecified.Unspecified',
  dependencies=[
    ':java7',
    ':lib',
  ],
)

java_library(name='lib',
  sources=globs('Unspecified.java'),
)

java_library(name='java7',
  sources=globs('Seven.java'),
  platform='java7',
  dependencies=[':lib'],
)
