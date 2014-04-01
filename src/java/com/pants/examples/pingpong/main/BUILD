# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='main',
  basename='pingpong',
  source='Main.java',
  main='com.pants.examples.pingpong.main.Main',
  dependencies=[
    pants('src/java/com/pants/examples/pingpong/handler')
  ]
)
