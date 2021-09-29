# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=[
      "*.py",
      "!*_test.py",
      "!dockerfile_parser.py",
      "!parser.py",
  ],
)

python_library(
  name="parser",
  sources=["parser.py"],
  dependencies=[":dockerfile_parser", ":lockfile"],
)

resources(name="lockfile", sources=["dockerfile_lockfile.txt"])

python_library(
  name="dockerfile_parser",
  sources=["dockerfile_parser.py"],
)

python_tests(
    name="tests",
    timeout=120,
)
