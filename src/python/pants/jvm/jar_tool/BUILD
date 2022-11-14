# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":jar_tool_src"])

python_tests(
    name="tests",
)

relocated_files(
    name="java_files",
    files_targets=[
        "//src/java/org/pantsbuild/args4j:src",
        "//src/java/org/pantsbuild/tools/jar:src",
    ],
    src="src/java",
    dest="src/python/pants/jvm/jar_tool/src",
)

resources(name="jar_tool_src", sources=["jar_tool.lock"], dependencies=[":java_files"])
