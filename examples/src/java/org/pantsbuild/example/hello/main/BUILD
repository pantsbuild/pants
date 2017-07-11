# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello World, but built with Pants.

# Note that the target has no explicit name, so it defaults to the name
# of the directory, in this case 'main'.
jvm_app(
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
    'examples/src/java/org/pantsbuild/example/hello/greet',
    'examples/src/resources/org/pantsbuild/example/hello',
  ],
  source = 'HelloMain.java',
  main = 'org.pantsbuild.example.hello.main.HelloMain',
  basename = 'hello-example',
)

# README page:

page(name="readme",
  source="README.md")

