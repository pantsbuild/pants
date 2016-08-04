# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

javac_plugin(
  name = 'simple_javac_plugin',
  sources = ['SimpleJavacPlugin.java'],
  dependencies = [],
  classname = 'org.pantsbuild.example.plugin.SimpleJavacPlugin',
  scope='compile',
)

java_library(
  name = 'hello_plugin',
  sources = ['HelloPlugin.java'],
  dependencies = [
    ':simple_javac_plugin'  # Plugin should run when compiling this target.
  ]
)
