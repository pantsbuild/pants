# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
    name = "compile-fail",
    main = "org.pantsbuild.testproject.runtime.CompileReference",
    source = "CompileReference.java",
    dependencies = [
        scoped(
            "3rdparty:gson",
            scope = "runtime",
        ),
    ],
)

jvm_binary(
    name = "compile-pass",
    main = "org.pantsbuild.testproject.runtime.CompileReference",
    source = "CompileReference.java",
    dependencies = [
        scoped(
            "3rdparty:gson",
            scope = "compile",
        ),
    ],
)

jvm_binary(
    name = "runtime-fail",
    main = "org.pantsbuild.testproject.runtime.RuntimeReference",
    source = "RuntimeReference.java",
    dependencies = [
        scoped(
            "3rdparty:gson",
            scope = "compile",
        ),
    ],
)

jvm_binary(
    name = "runtime-pass",
    main = "org.pantsbuild.testproject.runtime.RuntimeReference",
    source = "RuntimeReference.java",
    dependencies = [
        scoped(
            "3rdparty:gson",
            scope = "runtime",
        ),
    ],
)
