# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Demonstrates compiling code with a unicode classes

jvm_binary(name = 'main',
  basename = 'unicode-testproject',
  dependencies = [
    'src/java/com/pants/testproject/unicode/cucumber',
    'src/scala/com/pants/testproject/unicode/shapeless',
  ],
  source = 'CucumberMain.java',
  main = 'com.pants.testproject.unicode.main.CucumberMain',
)
