# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfiles"])

resources(name="lockfiles", sources=["*.lockfile.txt"])

python_tests(
    name="tests",
    dependencies=[":test_resources"],
    overrides={"rules_integration_test.py": {"timeout": 120}},
)

resources(name="test_resources", sources=["*.test.lock"])
