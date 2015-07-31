# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello World, but built with Pants.

jvm_binary(name = 'main',
  resources=[
    'contrib/npm_module/examples/src/resources/org/pantsbuild/example/less',
    'contrib/npm_module/examples/src/resources/org/pantsbuild/example/requirejs',
  ],
  source = 'HelloMain.java',
  main = 'org.pantsbuild.example.npm_module.HelloMain',
  basename = 'npm_module-example',
)

