# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    overrides={
        "java_scala_interop_test.py": {"timeout": 120},
        "artifact_mapper_test.py": {"timeout": 120},
    },
)
