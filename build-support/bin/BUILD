# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='common',
  sources='common.py',
  compatibility=['CPython>=3.6'],
)

python_binary(
  name='check_banned_imports',
  sources='check_banned_imports.py',
  dependencies=[
    ':common',
  ],
  compatibility=['CPython>=3.6'],
)

python_binary(
  name='check_header',
  sources='check_header.py',
  dependencies=[
    ':common',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta',
    '3rdparty/python/twitter/commons:twitter.common.collections',
  ],
  compatibility=['CPython>=3.6'],
)

python_binary(
  name='check_pants_pex_abi',
  sources='check_pants_pex_abi.py',
  dependencies=[
    ':common',
  ],
  compatibility=['CPython>=3.6'],
)

python_binary(
  name='shellcheck',
  sources='shellcheck.py',
  dependencies=[
    ':common',
  ],
  compatibility=['CPython>=3.6'],
)
