# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

annotation_processor(name='value',
  processors = [
    'com.google.auto.value.processor.AutoValueProcessor',
    'com.google.auto.value.processor.AutoValueBuilderProcessor',
    'com.google.auto.value.processor.AutoAnnotationProcessor',
  ],
  dependencies = [
    ':value-lib',
  ],
)

jar_library(name='value-lib',
  jars=[
    jar(org='com.google.auto.value', name='auto-value', rev='1.0'),
  ],
)
