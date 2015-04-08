# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
#  Example for annotation_processor() target

jvm_binary(name='main',
  source='Main.java',
  main='org.pantsbuild.example.annotation.main.Main',
  basename = 'annotation-example',
  dependencies=[
    'examples/src/java/org/pantsbuild/example/annotation/example',
    'examples/src/java/org/pantsbuild/example/annotation/processor',
  ],
)
