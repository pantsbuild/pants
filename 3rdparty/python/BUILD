# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see/edit requirements.txt in this directory to change deps.
python_requirements()

# Note: cannot currently be a dependencies() target, because that's just
# an alias for jar_library. 
# TODO: Make a real 'dependencies'/'alias' target type. 
python_library(name='antlr-3.1.3', dependencies=[':antlr-python-runtime'])
