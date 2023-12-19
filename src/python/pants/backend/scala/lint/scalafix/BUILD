# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])

python_tests(name="tests", dependencies=[":test_resources"])

resource(name="lockfile", source="scalafix.default.lockfile.txt")
resources(name="test_resources", sources=["*.test.lock"])
