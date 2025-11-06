# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(
    overrides={"rules.py": dict(dependencies=["./search_for_sonames.py"])},
)

python_tests(
    name="tests",
    overrides={"search_for_sonames_integration_test.py": dict(timeout=150)},
)
