# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name="init",
  sources=["__init__.py"],
)

python_binary(
  name='reversion',
  sources=["reversion.py"],
)

python_integration_tests(
  name='tests',
  dependencies=[
    'src/python/pants:reversion_file_with_dependencies',
  ],
  uses_pants_run=True,
)
