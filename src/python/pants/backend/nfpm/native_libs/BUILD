# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

resources(
    name="whl_samples_for_tests",
    sources=["*.whl"],
)

python_tests(
    name="tests",
    overrides={
        "rules_integration_test.py": dict(dependencies=[":whl_samples_for_tests"], timeout=150)
    },
)
