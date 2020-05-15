# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
  name = '3rdparty_directory',
  sources = ['3rdparty/**/*'],
)

# We use this to establish the build root, rather than `./pants`, because we cannot safely use the
# latter as the sentinel filename per https://github.com/pantsbuild/pants/pull/8105.
files(
  name = 'build_root',
  sources = ["BUILD_ROOT"],
)

files(
  name = 'build_tools',
  sources = ['BUILD.tools'],
)

files(
  name = 'gitignore',
  sources = ['.gitignore'],
)

files(
  name = 'isort_cfg',
  sources = ['.isort.cfg'],
)

files(
  name = 'pants_toml',
  sources = ['pants.toml'],
)

files(
  name = 'pyproject',
  sources = ['pyproject.toml'],
)

# NB: This is used for integration tests. This is generated automatically via `./pants` and
# `build-support/bin/bootstrap_pants_pex.sh`.
files(
  name = 'pants_pex',
  sources = ['pants.pex'],
)
