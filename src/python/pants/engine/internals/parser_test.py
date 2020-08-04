# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.parser import BuildFilePreludeSymbols, ParseError, Parser, SymbolTable
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.frozendict import FrozenDict


def test_imports_banned() -> None:
    parser = Parser(SymbolTable({}), BuildFileAliases())
    with pytest.raises(ParseError) as exc:
        parser.parse(
            "dir/BUILD", "\nx = 'hello'\n\nimport os\n", BuildFilePreludeSymbols(FrozenDict())
        )
    assert "Import used in dir/BUILD at line 4" in str(exc.value)


def test_unrecognized_symbol() -> None:
    parser = Parser(
        SymbolTable({"tgt": TargetAdaptor}),
        BuildFileAliases(
            objects={"obj": 0},
            context_aware_object_factories={"caof": lambda parse_context: lambda _: None},
        ),
    )
    prelude_symbols = BuildFilePreludeSymbols(FrozenDict({"prelude": 0}))
    with pytest.raises(ParseError) as exc:
        parser.parse("dir/BUILD", "fake", prelude_symbols)
    assert (
        str(exc.value)
        == "Name 'fake' is not defined.\n\nAll registered symbols: ['caof', 'obj', 'prelude', 'tgt']"
    )
