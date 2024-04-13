# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfiles"])

resources(name="lockfiles", sources=["*.default.lockfile.txt"])

python_tests(name="tests", dependencies=[":test-lockfiles"])

resources(name="test-lockfiles", sources=["*.test.lock"])
