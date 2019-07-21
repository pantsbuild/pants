# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name = 'check_banned_imports',
  source = 'check_banned_imports.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

files(
  name = 'check_clippy',
  source = 'check_clippy.sh'
)

python_binary(
  name = 'check_header',
  source = 'check_header.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

files(
  name = 'check_packages',
  source = 'check_packages.sh'
)

python_binary(
  name = 'check_pants_pex_abi',
  source = 'check_pants_pex_abi.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

files(
  name = 'check_rust_formatting',
  source = 'check_rust_formatting.sh'
)

files(
  name = 'check_rust_target_headers',
  source = 'check_rust_target_headers.sh'
)

files(
  name = 'check_shell',
  source = 'check_shell.sh'
)

python_binary(
  name = 'ci',
  source = 'ci.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

files(
  name = 'ci_failure',
  source = 'ci-failure.sh'
)

python_library(
  name = 'common',
  source = 'common.py',
  tags = {'type_checked'},
)

files(
  name = 'contributors',
  source = 'contributors.sh'
)

python_binary(
  name = 'deploy_to_s3',
  source = 'deploy_to_s3.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)

files(
  name = 'download_binary',
  source = 'download_binary.sh'
)

files(
  name = 'get_added_files',
  source = 'get_added_files.sh'
)

files(
  name = 'get_ci_bootstrapped_pants_pex',
  source = 'get_ci_bootstrapped_pants_pex.sh'
)

files(
  name = 'get_failing_travis_targets_for_pr',
  source = 'get_failing_travis_targets_for_pr.sh'
)

files(
  name = 'get_os',
  source = 'get_os.sh'
)

files(
  name = 'install_aws_cli_for_ci',
  source = 'install_aws_cli_for_ci.sh'
)

files(
  name = 'install_git_hooks',
  source = 'install_git_hooks.sh'
)

files(
  name = 'install_python_for_ci',
  source = 'install_python_for_ci.sh'
)

files(
  name = 'isort',
  source = 'isort.sh'
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

files(
  name = 'pre-commit',
  source = 'pre-commit.sh'
)

files(
  name = 'publish_docs',
  source = 'publish_docs.sh'
)

files(
  name = 'release',
  source = 'release.sh'
)

files(
  name = 'release-changelog-helper',
  source = 'release-changelog-helper.sh'
)

files(
  name = 'setup',
  source = 'setup.sh'
)

python_binary(
  name = 'shellcheck',
  source = 'shellcheck.py',
  dependencies = [
    ':common',
  ],
  tags = {'type_checked'},
)
