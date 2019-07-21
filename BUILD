# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
  name = 'build_tools',
  source = 'BUILD.tools',
)

files(
  name = '3rdparty_build',
  source = '3rdparty/BUILD',
)

# NB: Be careful when using this in tests! Some tests will use this to determine the buildroot and
# then dynamically try to open other files relative to the buildroot, such as BUILD.tools. This
# should not be used to dynamically import other files—those must be explicitly imported via their
# own BUILD entries.
files(
  name = 'pants_script',
  source = 'pants',
)
