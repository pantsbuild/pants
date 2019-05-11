# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'common',
  sources = 'common.py',
  compatibility = ['CPython>=3.6'],
)

python_binary(
  name = 'check_banned_imports',
  sources = 'check_banned_imports.py',
  compatibility = ['CPython>=3.6'],
)

python_binary(
  name = 'check_header_helper',
  sources = 'check_header_helper.py',
)

python_binary(
  name = 'check_pants_pex_abi',
  sources = 'check_pants_pex_abi.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
)

python_binary(
  name = 'mypy',
  sources = 'mypy.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
)
