# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='autovalue',
  main = 'com.pants.examples.autovalue.AutoValueMain',
  dependencies = [
    ':autovalue-lib',
  ]
)

java_library(name='autovalue-lib',
  sources = [ 'AutoValueMain.java' ],
  dependencies = [
    '3rdparty:auto-value',
  ],
)

annotation_processor(name='auto-value-processor',
  sources = [],
  processors = [
    'com.google.auto.value.processor.AutoValueProcessor',
    'com.google.auto.value.processor.AutoValueBuilderProcessor',
    'com.google.auto.value.processor.AutoAnnotationProcessor',
  ],
  dependencies = [
    '3rdparty:auto-value',
  ],
)
