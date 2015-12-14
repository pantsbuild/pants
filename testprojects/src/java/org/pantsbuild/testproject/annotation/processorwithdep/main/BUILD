# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


jvm_binary(name='main',
  source = 'Main.java',
  main = 'org.pantsbuild.testproject.annotation.processorwithdep.Main',
  basename = 'processorwithdep-main',
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject/annotation/processorwithdep/hellomaker',
    'testprojects/src/java/org/pantsbuild/testproject/annotation/processorwithdep/processor',
  ],
)
