# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see/edit requirements.txt in this directory to change deps.
python_requirements(
  module_mapping={
    "ansicolors": ["colors"],
    "beautifulsoup4": ["bs4"],
    "packaging": ["pkgutil"],
    "python-Levenshtein": ["Levenshtein"],
    "PyYAML": ["yaml"],
    "setuptools": ["pkg_resources"],
  }
)

# Only used by a maintenance tool, so we lift this library out of the requirements.txt
# file used to bootstrap pants itself.
python_requirement_library(
  name='s3logparse',
  requirements=[
    python_requirement('s3-log-parse==0.1.1', modules=['s3logparse'])
  ]
)
