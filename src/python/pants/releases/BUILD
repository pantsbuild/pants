# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name = 'reversion',
  sources = ['reversion.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

# Note that packages.py is not part of a target, it should be run with pex.
# Its dependencies and such can be found in build-support/bin/release.sh.
