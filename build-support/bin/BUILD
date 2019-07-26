# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
  name = 'bash_scripts',
  sources = globs('*.sh'),
)

python_binary(
  name = 'check_banned_imports',
  source = 'check_banned_imports.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'check_header',
  source = 'check_header.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'check_pants_pex_abi',
  source = 'check_pants_pex_abi.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'ci',
  source = 'ci.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_library(
  name = 'common',
  source = 'common.py',
  tags = {'type_checked'},
)

python_binary(
  name = 'deploy_to_s3',
  source = 'deploy_to_s3.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'get_rbe_token',
  sources = 'get_rbe_token.py',
  dependencies = [
    '3rdparty/python:ansicolors',
    '3rdparty/python:requests',
  ],
  tags = {'type_checked'},
)

python_binary(
  name = 'mypy',
  source = 'mypy.py',
  tags = {'type_checked'},
)

python_binary(
  name = 'shellcheck',
  source = 'shellcheck.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)
