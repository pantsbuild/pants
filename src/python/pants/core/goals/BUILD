# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    sources=["*_test.py", "!*_integration_test.py"],
    overrides={
        "publish_test.py": {"timeout": 70},
    },
)

python_tests(
    name="integration",
    sources=["*_integration_test.py"],
    dependencies=["testprojects/src/python:hello_directory"],
    timeout=240,
)
