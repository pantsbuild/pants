# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    dependencies=[":lockfiles"],
    timeout=600,
)

resources(name="lockfiles", sources=["*.test.lock"])
