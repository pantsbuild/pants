# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'common',
  sources = 'common.py',
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)

python_binary(
  name = 'check_banned_imports',
  sources = 'check_banned_imports.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)

python_binary(
  name = 'check_header',
  sources = 'check_header.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)

python_binary(
  name = 'check_pants_pex_abi',
  sources = 'check_pants_pex_abi.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)

python_binary(
  name = 'ci',
  sources = 'ci.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)

python_binary(
  name = 'deploy_to_s3',
  sources = 'deploy_to_s3.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)

python_binary(
  name = 'mypy',
  sources = 'mypy.py',
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)

python_binary(
  name = 'shellcheck',
  sources = 'shellcheck.py',
  dependencies = [
    ':common',
  ],
  compatibility = ['CPython>=3.6'],
  tags = {'type_checked'},
)
