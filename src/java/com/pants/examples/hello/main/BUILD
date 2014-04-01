# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello world, but built with Pants.

jvm_binary(name = 'main',
  dependencies = [
    pants('src/java/com/pants/examples/hello/greet'),
  ],
  source = 'HelloMain.java',
  main = 'com.pants.examples.hello.main.HelloMain',
)
