# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.parser import BuildFilePreludeSymbols, ParseError, Parser
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict


def test_imports_banned() -> None:
    parser = Parser(build_root="", target_type_aliases=[], object_aliases=BuildFileAliases())
    with pytest.raises(ParseError) as exc:
        parser.parse(
            "dir/BUILD", "\nx = 'hello'\n\nimport os\n", BuildFilePreludeSymbols(FrozenDict())
        )
    assert "Import used in dir/BUILD at line 4" in str(exc.value)


def test_unrecogonized_symbol() -> None:
    def perform_test(extra_targets: list[str], dym: str) -> None:

        parser = Parser(
            build_root="",
            target_type_aliases=["tgt", *extra_targets],
            object_aliases=BuildFileAliases(
                objects={"obj": 0},
                context_aware_object_factories={"caof": lambda parse_context: lambda _: None},
            ),
        )
        prelude_symbols = BuildFilePreludeSymbols(FrozenDict({"prelude": 0}))
        fmt_extra_sym = str(extra_targets)[1:-1] + (", ") if len(extra_targets) != 0 else ""
        with pytest.raises(ParseError) as exc:
            parser.parse("dir/BUILD", "fake", prelude_symbols)
        assert str(exc.value) == (
            f"Name 'fake' is not defined.\n\n{dym}"
            "If you expect to see more symbols activated in the below list,"
            f" refer to {doc_url('enabling-backends')} for all available"
            " backends to activate.\n\n"
            f"All registered symbols: ['caof', {fmt_extra_sym}'obj', 'prelude', 'tgt']"
        )

    test_targs = ["fake1", "fake2", "fake3", "fake4", "fake5"]

    perform_test([], "")
    dym_one = "Did you mean fake1?\n\n"
    perform_test(test_targs[:1], dym_one)
    dym_two = "Did you mean fake2 or fake1?\n\n"
    perform_test(test_targs[:2], dym_two)
    dym_many = "Did you mean fake5, fake4, or fake3?\n\n"
    perform_test(test_targs, dym_many)
