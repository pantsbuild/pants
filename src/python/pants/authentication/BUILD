# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.authentication.netrc_util import Netrc

netrc = Netrc()

credentials(
  name = 'netrc',
  username=netrc.getusername,
  password=netrc.getpassword)

python_library(
  name = 'authentication',
  sources = globs('*.py'),
)
