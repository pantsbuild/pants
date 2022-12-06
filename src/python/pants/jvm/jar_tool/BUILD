# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":jar_tool_src"])

python_tests(
    name="tests",
)

resources(
    name="jar_tool_src",
    sources=["jar_tool.lock"],
    dependencies=["./args4j:src", "./jar_tool_source:src"],
)
