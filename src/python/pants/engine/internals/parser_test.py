# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.defaults import BuildFileDefaults, BuildFileDefaultsParserState
from pants.engine.internals.parser import (
    BuildFilePreludeSymbols,
    ParseError,
    Parser,
    _extract_symbol_from_name_error,
)
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.testutil.pytest_util import no_exception
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict


@pytest.fixture
def defaults_parser_state() -> BuildFileDefaultsParserState:
    return BuildFileDefaultsParserState.create(
        "", BuildFileDefaults({}), RegisteredTargetTypes({}), UnionMembership({})
    )


def test_imports_banned(defaults_parser_state: BuildFileDefaultsParserState) -> None:
    parser = Parser(
        build_root="",
        target_type_aliases=[],
        object_aliases=BuildFileAliases(),
        ignore_unrecognized_symbols=False,
    )
    with pytest.raises(ParseError) as exc:
        parser.parse(
            "dir/BUILD",
            "\nx = 'hello'\n\nimport os\n",
            BuildFilePreludeSymbols(FrozenDict()),
            False,
            defaults_parser_state,
        )
    assert "Import used in dir/BUILD at line 4" in str(exc.value)


def test_unrecognized_symbol(defaults_parser_state: BuildFileDefaultsParserState) -> None:
    build_file_aliases = BuildFileAliases(
        objects={"obj": 0},
        context_aware_object_factories={"caof": lambda parse_context: lambda _: None},
    )

    def perform_test(extra_targets: list[str], dym: str) -> None:
        parser = Parser(
            build_root="",
            target_type_aliases=["tgt", *extra_targets],
            object_aliases=build_file_aliases,
            ignore_unrecognized_symbols=False,
        )
        prelude_symbols = BuildFilePreludeSymbols(FrozenDict({"prelude": 0}))
        fmt_extra_sym = str(extra_targets)[1:-1] + (", ") if len(extra_targets) != 0 else ""
        with pytest.raises(ParseError) as exc:
            parser.parse(
                "dir/BUILD",
                "fake",
                prelude_symbols,
                False,
                defaults_parser_state,
            )
        assert str(exc.value) == (
            f"Name 'fake' is not defined.\n\n{dym}"
            "If you expect to see more symbols activated in the below list,"
            f" refer to {doc_url('enabling-backends')} for all available"
            " backends to activate.\n\n"
            f"All registered symbols: ['__defaults__', 'build_file_dir', 'caof', {fmt_extra_sym}"
            "'obj', 'prelude', 'tgt']"
        )

        with no_exception():
            parser = Parser(
                build_root="",
                target_type_aliases=["tgt", *extra_targets],
                object_aliases=build_file_aliases,
                ignore_unrecognized_symbols=True,
            )
            parser.parse(
                "dir/BUILD",
                "fake",
                prelude_symbols,
                False,
                defaults_parser_state,
            )

    test_targs = ["fake1", "fake2", "fake3", "fake4", "fake5"]

    perform_test([], "")
    dym_one = "Did you mean fake1?\n\n"
    perform_test(test_targs[:1], dym_one)
    dym_two = "Did you mean fake2 or fake1?\n\n"
    perform_test(test_targs[:2], dym_two)
    dym_many = "Did you mean fake5, fake4, or fake3?\n\n"
    perform_test(test_targs, dym_many)


@pytest.mark.parametrize("symbol", ["a", "bad", "BAD", "a___b_c", "a231", "áç"])
def test_extract_symbol_from_name_error(symbol: str) -> None:
    assert _extract_symbol_from_name_error(NameError(f"name '{symbol}' is not defined")) == symbol
