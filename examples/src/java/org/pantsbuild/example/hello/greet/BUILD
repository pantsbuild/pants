# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Note that the target has no explicit name, so it defaults to the name
# of the directory, in this case 'greet'.
java_library(
  dependencies = [], # A more realistic example would depend on other libs,
                     # but this "hello world" is pretty simple.
  sources = globs('*.java'),
  provides = artifact(org='org.pantsbuild.example',
                      name='hello-greet',
                      repo=public,),
)
