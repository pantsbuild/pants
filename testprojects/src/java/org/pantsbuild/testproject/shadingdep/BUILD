# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
    basename = "shadingdep",
    main = "org.pantsbuild.testproject.shadingdep.Dependency",
    dependencies = [
        ":lib",
        "testprojects/src/java/org/pantsbuild/testproject/shadingdep/subpackage",
    ],
)

jvm_binary(
    name = "other",
    basename = "other",
    main = "org.pantsbuild.testproject.shadingdep.otherpackage.ShadeWithTargetId",
    dependencies = [
        "testprojects/src/java/org/pantsbuild/testproject/shadingdep/otherpackage",
    ],
)

java_library(name = "lib")
