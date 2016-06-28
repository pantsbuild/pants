# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
#  Example of annotation_processor() target

annotation_processor(name='processor',
  sources=['ExampleProcessor.java'],
  processors=['org.pantsbuild.example.annotation.processor.ExampleProcessor'],
  dependencies=[
    'examples/src/java/org/pantsbuild/example/annotation/example',
    '3rdparty:guava',
  ],
  scope='forced',
)
