# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello World, but built with Pants.

jvm_app(name='main',
  basename = 'hello-example',
  dependencies = [
    ':main-bin'
  ],
)

# The binary, the "runnable" part:

jvm_binary(name = 'main-bin',
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet',
  ],
  source = 'HelloMain.java',
  main = 'org.pantsbuild.testproject.publish.hello.main.HelloMain',
  basename = 'hello-example',
)
