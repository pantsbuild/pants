# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'mypy-passing-examples',
  sources = ['dataclasses_mypy_success.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
  ],
  tags = {'extra_type_checked'},
)

python_library(
  name = 'mypy-failing-examples',
  sources = ['dataclasses_mypy_failure.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
  ],
  tags = {'extra_type_checked'},
)
