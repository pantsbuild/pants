# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_antlr_library(
  name = 'eval',
  module = 'pants.backend.python.test',
  sources = ['Eval.g', 'Expr.g'],
)

python_antlr_library(
  name = 'csv',
  module = 'pants.backend.python.test2',
  sources = ['csv.g'],
)

# This target is intended to fail inside antlr, because
# bogus.g is not a valid antlr grammar.
python_antlr_library(
  name = 'antlr_failure',
  module = 'pants.backend.python.test3',
  sources = ['bogus.g'],
)
