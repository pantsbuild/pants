# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see test_idea_integration.py
junit_tests(
  name='code',
  sources = ['TestResourcesAndCode.java'],
  resources=[
      ':readme',
      # Add a direct dependency on a non-test resources folder
      # to make sure it stays non-test resources
      'testprojects/src/resources/org/pantsbuild/testproject/ideacodeandresources:resource',
      'testprojects/tests/resources/org/pantsbuild/testproject/ideacodeandresources:resource',
   ],
  dependencies=[
    '3rdparty:junit',
  ]
)

resources(
  name='readme',
  sources=['README.md'],
)

