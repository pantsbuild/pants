# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
    sources = globs("*.py"),
    dependencies = [
        ":text",
    ],
)

resources(
    name = "text",
    sources = globs("*.txt"),
)

resources(
    name = "missing-globs",
    sources = globs("*.a"),
)

resources(
    name = "missing-rglobs",
    sources = rglobs("*.a"),
)

resources(
    name = "missing-zglobs",
    sources = zglobs("**/*.a"),
)

resources(
    name = "missing-literal-files",
    sources = [
        "another_nonexistent_file.txt",
        "nonexistent_test_file.txt",
    ],
)

resources(
    name = "some-missing-some-not",
    sources = globs("*.txt", "*.rs"),
)

resources(
    name = "overlapping-globs",
    sources = globs("sources.txt", "*.txt"),
)
