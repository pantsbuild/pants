# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=[
    "*.py",
    "!*_test.py",
    "!dependency_inference.py",
    "!hcl2_parser.py"
  ],
)

python_library(
  name="dependency_inference",
  sources=["dependency_inference.py"],
  dependencies=[":hcl2_parser", ":lockfile"],
)

python_library(
  name="hcl2_parser",
  sources=["hcl2_parser.py"],
)

resources(name="lockfile", sources=["hcl2_lockfile.txt"])

python_tests(name='tests', sources=["*_test.py", "!dependency_inference_test.py"])
python_tests(
  name="dependency_inference_test",
  sources=["dependency_inference_test.py"],
  timeout=240,
  # We want to make sure the default lockfile works for both macOS and Linux.
  tags=["platform_specific_behavior"],
)
