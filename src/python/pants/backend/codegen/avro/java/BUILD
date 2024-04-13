# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])

resource(name="lockfile", source="avro-tools.default.lockfile.txt")

python_tests(
    name="tests",
    dependencies=[":test_lockfiles"],
    overrides={"rules_integration_test.py": {"timeout": 120}},
)

resources(name="test_lockfiles", sources=["*.test.lock"])
