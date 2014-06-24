# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello World, but built with Pants.

jvm_app(name='main',
  dependencies = [
    ':main-bin'
  ],
  bundles = [
    bundle(relative_to='config').add(globs('config/*'))
  ]
)

# The binary, the "runnable" part:

jvm_binary(name = 'main-bin',
  dependencies = [
    pants('src/java/com/pants/examples/hello/greet'),
  ],
  resources=[
    pants('src/resources/com/pants/example/hello'),
  ],
  source = 'HelloMain.java',
  main = 'com.pants.examples.hello.main.HelloMain',
)

# README page:

page(name="readme",
  source="README.md")

