# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: We cannot depend on `./pants`. When running tests with V1, the folder in `.pants.d` will strip
# the prefix so `src/python/pants` -> `pants`. You cannot both have a directory named `pants` and a
# file named `pants`, so this causes most V1 tests to fail.

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
  source = 'pants.ini'
)
