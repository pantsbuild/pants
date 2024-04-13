# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resource(name="lockfile", source="junit.default.lockfile.txt")

python_tests(name="tests", timeout=240, dependencies=[":test_resources"])
resources(name="test_resources", sources=["*.test.lock"])
