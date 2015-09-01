# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see test_idea_integration.py
java_library(
  name='lib',
  sources = ['LibraryExample.java'],
)

junit_tests(
  name='test',
  sources = ['TestExample.java'],
  dependencies = [
    '3rdparty:junit',
  ]
)

