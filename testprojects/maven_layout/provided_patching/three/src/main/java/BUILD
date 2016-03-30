# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='shadow',
  sources=[
    'org/pantsbuild/testproject/provided_patching/Shadow.java',
  ],
)

java_library(name='common',
  sources=[
    'org/pantsbuild/testproject/provided_patching/Common.java',
  ],
  dependencies=[
    provided(':shadow'),
  ],
)
