# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=["*.py", "!cmd_line_spec_parser.py", "!specs.py", "!*_test.py"],
)

python_library(
  name="specs",
  sources=["cmd_line_spec_parser.py", "specs.py"],
)

python_tests(name='tests')
