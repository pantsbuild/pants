# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    timeout=120,
    overrides={
        "deployment_test.py": {
            "tags": ["platform_specific_behavior"],
        }
    },
)
