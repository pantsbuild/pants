# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see/edit requirements.txt in this directory to change deps.
python_requirements()

# Only used by tests, so we lift this library out of the requirements.txt
# file used to bootstrap pants itself.
python_requirement_library(
  name='antlr4',
  requirements=[
    # TODO: this library is not currently linked from pypi, so we override the repository
    # to fetch it from antlr.org instead. If at any point it reappears on pypi, the
    # repository arg can be removed.
    python_requirement('antlr4-python3-runtime==4.7.2')
  ]
)

# Only used by a maintenance tool, so we lift this library out of the requirements.txt
# file used to bootstrap pants itself.
python_requirement_library(
  name='s3logparse',
  requirements=[
    python_requirement('s3-log-parse==0.1.1')
  ]
)
