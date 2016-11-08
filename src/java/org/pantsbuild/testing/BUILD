# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  # We have to use explicit sources here to grab `EasyMockTest.java` which otherwise gets excluded.
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:easymock',
    '3rdparty:guava',
    '3rdparty:guava-testlib',
    '3rdparty:junit'
  ],
  platform='java7',
)
