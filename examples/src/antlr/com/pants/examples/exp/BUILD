# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(name='exp',
  dependencies=[
    ':exp_antlr3',
    ':exp_antlr4',
  ]
)

java_antlr_library(name='exp_antlr3',
  sources=['ExpAntlr3.g'],
  compiler='antlr3',
)

java_antlr_library(name='exp_antlr4',
  sources=['ExpAntlr4.g'],
  compiler='antlr4',
)
