# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see test_idea_integration.py
java_library(
  name='code',
  sources = ['ResourcesAndCode.java'],
  resources=[
      ':readme',
      'testprojects/src/resources/org/pantsbuild/testproject/ideacodeandresources:resource',
   ],
)

resources(
  name='readme',
  sources=['README.md'],
)

