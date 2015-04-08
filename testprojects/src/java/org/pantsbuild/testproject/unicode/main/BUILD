# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Demonstrates compiling code with a unicode classes

jvm_binary(name = 'main',
  basename = 'unicode-testproject',
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject/unicode/cucumber',
    'testprojects/src/scala/org/pantsbuild/testproject/unicode/shapeless',
  ],
  source = 'CucumberMain.java',
  main = 'org.pantsbuild.testproject.unicode.main.CucumberMain',
)
