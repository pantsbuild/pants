# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile"])
resources(name="lockfile", sources=["ktlint.default.lockfile.txt"])

python_tests(name="tests", timeout=120)

