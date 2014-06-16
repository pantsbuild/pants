# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='cucumber',
  sources=globs('*.java'),
  dependencies = [
    ':info.cukes.cucumber-java',
  ],
)

jar_library(name='info.cukes.cucumber-java',
    jars=[
      jar(org='info.cukes',
          name='cucumber-java',
          rev='1.1.7'),
    ],
)
