# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(dependencies=[":lockfile"])

resources(name="lockfile", sources=["hcl2_lockfile.txt"])

python_tests(name='tests', sources=["*_test.py", "!dependency_inference_test.py"])
python_tests(
  name="dependency_inference_test",
  sources=["dependency_inference_test.py"],
  timeout=240,
  # We want to make sure the default lockfile works for both macOS and Linux.
  tags=["platform_specific_behavior"],
)
