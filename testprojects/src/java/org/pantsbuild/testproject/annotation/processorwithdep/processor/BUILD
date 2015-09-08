# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
#  annotation_processor() target to test generating java code

annotation_processor(name = 'processor',
  sources = globs('*.java'),
  processors = ['org.pantsbuild.testproject.annotation.processorwithdep.processor.ProcessorWithDep'],
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject/annotation/processorwithdep/hellomaker',
    ':javapoet',
  ],
)

jar_library(
  name = 'javapoet',
  jars = [
    jar(org='com.squareup', name='javapoet', rev='1.2.0'),
  ],
)
