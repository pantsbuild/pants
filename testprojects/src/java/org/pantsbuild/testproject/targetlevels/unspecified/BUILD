# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='unspecified',
  main='org.pantsbuild.testproject.targetlevels.unspecified.Unspecified',
  dependencies=[
    ':java6',
    ':lib',
  ],
)

java_library(name='lib',
  sources=globs('Unspecified.java'),
)

java_library(name='java6',
  sources=globs('Six.java'),
  platform='java6',
  dependencies=[':lib'],
)