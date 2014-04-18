# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello world, but built with Pants.

jvm_app(name='main',
  binary=(':main-bin'),
  bundles=bundle(relative_to='config').add(globs('config/*'))
)

jvm_binary(name = 'main-bin',
  dependencies = [
    pants('src/java/com/pants/examples/hello/greet'),
    pants('3rdparty:log4j'),
  ],
  source = 'HelloMain.java',
  main = 'com.pants.examples.hello.main.HelloMain',
)
