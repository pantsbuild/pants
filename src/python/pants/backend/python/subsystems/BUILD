# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(dependencies=[":lockfiles"])
resources(name="lockfiles", sources=["*_lockfile.txt"])

python_tests(name="tests", timeout=120)
