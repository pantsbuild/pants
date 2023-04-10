# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()
python_tests(
    name="tests",
    overrides={
        "package_binary_integration_test.py": {"timeout": 120},
        "run_binary_integration_test.py": {"timeout": 120},
        "test_test.py": {"timeout": 480},
    },
)
