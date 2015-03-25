# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see/edit requirements.txt in this directory to change deps.
python_requirements()

# Only used by tests so we lift this library out of the requirements.txt
# file used to bootstrap pants itself.
python_requirement_library(
  name='antlr-3.1.3',
  requirements=[
    python_requirement('antlr_python_runtime==3.1.3')
  ]
)
