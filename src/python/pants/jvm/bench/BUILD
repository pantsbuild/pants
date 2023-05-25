# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resource(name="lockfile", source="jmh.default.lockfile.txt")

python_tests(name="tests", dependencies=[":test_resources"])
resources(name="test_resources", sources=["*.test.lock"])
