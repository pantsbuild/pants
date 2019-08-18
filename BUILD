# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# We use this to establish the build root, rather than `./pants`, because we cannot safely use the
# latter as the sentinel filename per https://github.com/pantsbuild/pants/pull/8105.
files(
  name = 'build_root',
  source = "BUILD_ROOT",
)

files(
  name = 'build_tools',
  source = 'BUILD.tools',
)

files(
  name = '3rdparty_build',
  source = '3rdparty/BUILD',
)

files(
  name = 'pants_ini',
  source = 'pants.ini',
)

# NB: THis is used for integration tests. This is a generated file not tracked by VCS, and it is
# easy to fall out of sync. To generate, run `build-support/bin/ci.py --bootstrap`. Ideally
# we will be able to design a mechanism to ensure that the PEX is up-to-date.
files(
  name = 'pants_pex',
  source = 'pants.pex',
)
