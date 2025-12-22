# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    overrides={
        "docutil_integration_test.py": {
            "dependencies": ["testprojects/src/python:hello_directory"],
            "timeout": 240,
        }
    },
)
