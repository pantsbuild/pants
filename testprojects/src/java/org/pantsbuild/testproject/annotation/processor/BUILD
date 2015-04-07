# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
#  annotation_processor() target to test resource mapping

annotation_processor(name='processor',
  sources=globs('*.java'),
  processors=['org.pantsbuild.testproject.annotation.processor.ResourceMappingProcessor'],
  dependencies=[
    '3rdparty:guava',
  ],
)

