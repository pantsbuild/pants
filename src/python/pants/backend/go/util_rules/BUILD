# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(dependencies=[":analyzer_sources"])
python_tests(name='tests', timeout=120)

resources(
  name="analyzer_sources",
  sources=["analyze_test_sources.go"],
)
