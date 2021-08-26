# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name="coverage_py_integration",
  sources=["coverage_py_integration_test.py"],
  # We want to make sure the default lockfile works for both macOS and Linux.
  tags=["platform_specific_behavior"],
  timeout=210,
)

python_tests(name="coverage_py_test", sources=["coverage_py_test.py"], timeout=20)

python_tests(
    name="package_pex_binary_integration",
    sources=["package_pex_binary_integration_test.py"],
    timeout=120,
)

python_tests(
  name="pytest_runner_integration",
  sources=["pytest_runner_integration_test.py"],
  # We want to make sure the default lockfile works for both macOS and Linux.
  tags=["platform_specific_behavior"],
  timeout=480,
)

python_tests(
    name="run_pex_binary_integration",
    sources=["run_pex_binary_integration_test.py"],
    timeout=120,
)

python_tests(
  name="setup_py_integration",
  sources=["setup_py_integration_test.py"],
  dependencies=["testprojects/src/python:native_directory"],
  timeout=180,
)

python_tests(
    name="setup_py_test",
    sources=["setup_py_test.py"],
    timeout=150,
)

python_tests(name="tailor_test", sources=["tailor_test.py"])
