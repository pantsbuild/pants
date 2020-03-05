# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='exclude_literal_files',
  sources=['**/*.py', '!aaa.py', '!dir1/aaa.py'],
)

python_library(
  name='exclude_globs',
  sources=['**/*.py', '!*bb.py', '!dir1/dirdir1/*aa.py'],
)

python_library(
  name='exclude_recursive_globs',
  sources=['**/*.py', '!**/*b.py'],
)

python_library(
  name='implicit_sources',
)

python_tests(
  name='test_with_implicit_sources',
)
