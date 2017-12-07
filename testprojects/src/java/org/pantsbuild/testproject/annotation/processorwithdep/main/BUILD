# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
    basename = "processorwithdep-main",
    main = "org.pantsbuild.testproject.annotation.processorwithdep.Main",
    source = "Main.java",
    dependencies = [
        "testprojects/src/java/org/pantsbuild/testproject/annotation/processorwithdep/hellomaker",
        "testprojects/src/java/org/pantsbuild/testproject/annotation/processorwithdep/processor",
    ],
)
