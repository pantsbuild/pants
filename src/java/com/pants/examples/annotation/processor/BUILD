# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
#  Example of annotation_processor() target

annotation_processor(name='processor',
  sources = [
    'ExampleProcessor.java',
  ],
  processors = [
    'com.pants.examples.annotation.processor.ExampleProcessor',
  ],
  dependencies = [
    '3rdparty/jvm/guava',
    'src/java/com/pants/examples/annotation/example',
  ],
)
