# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  dependencies=[
    ':exp_antlr3',
    ':exp_antlr4',
    ':exp_antlr4_fork'
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

java_antlr_library(name='exp_antlr4_fork',
  sources=['ExpAntlr4.g'],
  compiler='antlr4_fork',
)
