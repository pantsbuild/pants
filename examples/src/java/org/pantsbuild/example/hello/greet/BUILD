# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name = 'greet',
  dependencies = [], # A more realistic example would depend on other libs,
                     # but this "hello world" is pretty simple.
  sources = globs('*.java'),
  provides = artifact(org='org.pantsbuild.example',
                      name='hello-greet',
                      repo=public,),
)
