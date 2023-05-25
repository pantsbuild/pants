# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resources(name="lockfile", sources=["jmh.default.lockfile.txt"])

python_tests(name="tests", dependencies=[":test_lockfile"])
resources(name="test_lockfile", sources=["jmh.test.lock"])
