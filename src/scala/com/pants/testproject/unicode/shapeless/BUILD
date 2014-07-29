# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(name='com.chuusai.shapeless',
  jars=[
    jar(org='com.chuusai', name='shapeless_2.9.2', rev='1.2.4')
  ],
)

scala_library(name='shapeless',
  sources=globs('*.scala'),
  dependencies = [
    ':com.chuusai.shapeless',
  ],
)
