# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={"rules.py": dict(dependencies=["./search_for_sonames.py"])},
)

python_tests(
    name="tests",
    sources=["*_test.py"],
    overrides={"search_for_sonames_integration_test.py": dict(timeout=150)},
)

python_test_utils(
    name="test_utils",
    sources=["test_utils.py"],
)
