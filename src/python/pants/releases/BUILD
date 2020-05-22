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

# While this is a target, it should be run with pex. See build-support/bin/release.sh.
python_binary(
  name = "packages",
  sources = ["packages.py"],
  tags = {"type_checked"},
)
