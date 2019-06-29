# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'common',
  sources = 'common.py',
  tags = {'type_checked'},
)

python_binary(
  name = 'check_banned_imports',
  sources = 'check_banned_imports.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'check_header',
  sources = 'check_header.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'check_pants_pex_abi',
  sources = 'check_pants_pex_abi.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'ci',
  sources = 'ci.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'deploy_to_s3',
  sources = 'deploy_to_s3.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'mypy',
  sources = 'mypy.py',
  tags = {'type_checked'},
)

python_binary(
  name = 'shellcheck',
  sources = 'shellcheck.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)
