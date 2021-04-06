# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name="tests",
  dependencies=[
    # We shell out to pex in tests; so we have a dependency, but not an explicit import.
    "3rdparty/python:pex",
  ],
  timeout=90,
)
