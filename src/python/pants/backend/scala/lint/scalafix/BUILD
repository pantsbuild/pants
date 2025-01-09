# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])

python_tests(name="tests", dependencies=[":test-lockfiles"])

resource(name="lockfile", source="scalafix.default.lockfile.txt")

resources(name="test-lockfiles", sources=["*.test.lock"])
