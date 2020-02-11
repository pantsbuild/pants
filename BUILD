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
  source = "BUILD_ROOT",
)

files(
  name = 'build_tools',
  source = 'BUILD.tools',
  dependencies = [
    ':scalajs_3rdparty_directory',
  ],
)

files(
  name = 'gitignore',
  source = '.gitignore',
)

files(
  name = 'isort_cfg',
  source = '.isort.cfg',
)

files(
  name = 'scalajs_3rdparty_directory',
  sources = ['contrib/scalajs/3rdparty/**/*'],
)

files(
  name = 'pants_toml',
  source = 'pants.toml',
)

files(
  name = 'pyproject',
  source = 'pyproject.toml',
)

# NB: This is used for integration tests. This is generated automatically via `./pants` and
# `build-support/bin/bootstrap_pants_pex.sh`.
files(
  name = 'pants_pex',
  source = 'pants.pex',
)
