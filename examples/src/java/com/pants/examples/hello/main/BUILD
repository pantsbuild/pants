# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello World, but built with Pants.

jvm_app(name='main',
  basename = 'hello-example',
  dependencies = [
    ':main-bin'
  ],
  bundles = [
    bundle(relative_to='config', fileset=globs('config/*'))
  ]
)

# The binary, the "runnable" part:

jvm_binary(name = 'main-bin',
  dependencies = [
    'examples/src/java/com/pants/examples/hello/greet',
  ],
  resources=[
    'examples/src/resources/com/pants/examples/hello',
  ],
  source = 'HelloMain.java',
  main = 'com.pants.examples.hello.main.HelloMain',
  basename = 'hello-example',
)

# README page:

page(name="readme",
  source="README.md")

