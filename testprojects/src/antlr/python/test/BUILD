# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_antlr_library(
    name = "eval",
    sources = [
        "Eval.g",
        "Expr.g",
    ],
    module = "pants_antlr.test.eval",
)

# This target is intended to fail inside antlr, because
# bogus.g is not a valid antlr grammar.
python_antlr_library(
    name = "antlr_failure",
    sources = ["bogus.g"],
    module = "pants_antlr.test.bogus",
)
