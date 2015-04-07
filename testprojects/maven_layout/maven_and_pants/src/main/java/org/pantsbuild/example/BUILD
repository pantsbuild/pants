# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='lib',
  sources = ['HelloMavenAndPants.java'],
)

jvm_binary(name='example',
  basename = 'hello-maven-and-pants',
  main = 'org.pantsbuild.example.HelloMavenAndPants',
  dependencies = [':lib'],
)
