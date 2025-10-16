# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
python_sources()
python_tests(
    name="tests",
    timeout=180,
    overrides={
        "check_test.py": {"dependencies": ["//src/python/pants/backend/typescript:test_resources"]},
    },
)
