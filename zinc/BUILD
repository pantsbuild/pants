# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
    name = "compiler",
    main = "org.pantsbuild.zinc.compiler.Main",
    description = "zinc compiler -- the scala compiler in nailgun",
    dependencies = [
        "src/scala/org/pantsbuild/zinc/compiler",
    ],
)

jvm_binary(
    name = "extractor",
    main = "org.pantsbuild.zinc.extractor.Main",
    description = "zinc extractor -- extractor for zinc analysis",
    dependencies = [
        "src/scala/org/pantsbuild/zinc/extractor",
    ],
)
