# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent
from typing import Any

import pytest

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.engine.env_vars import EnvironmentVars
from pants.engine.internals.defaults import BuildFileDefaults, BuildFileDefaultsParserState
from pants.engine.internals.parser import (
    BuildFilePreludeSymbols,
    ParseError,
    Parser,
    _extract_symbol_from_name_error,
)
from pants.engine.target import InvalidFieldException, RegisteredTargetTypes, StringField
from pants.engine.unions import UnionMembership
from pants.testutil.pytest_util import no_exception
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


@pytest.fixture
def defaults_parser_state() -> BuildFileDefaultsParserState:
    return BuildFileDefaultsParserState.create(
        "", BuildFileDefaults({}), RegisteredTargetTypes({}), UnionMembership({})
    )


def test_imports_banned(defaults_parser_state: BuildFileDefaultsParserState) -> None:
    parser = Parser(
        build_root="",
        registered_target_types=RegisteredTargetTypes({}),
        union_membership=UnionMembership({}),
        object_aliases=BuildFileAliases(),
        ignore_unrecognized_symbols=False,
    )
    with pytest.raises(ParseError) as exc:
        parser.parse(
            "dir/BUILD",
            "\nx = 'hello'\n\nimport os\n",
            BuildFilePreludeSymbols(FrozenDict(), ()),
            EnvironmentVars({}),
            False,
            defaults_parser_state,
            dependents_rules=None,
            dependencies_rules=None,
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
            registered_target_types=RegisteredTargetTypes(
                {alias: GenericTarget for alias in ("tgt", *extra_targets)}
            ),
            union_membership=UnionMembership({}),
            object_aliases=build_file_aliases,
            ignore_unrecognized_symbols=False,
        )
        prelude_symbols = BuildFilePreludeSymbols.create({"prelude": 0}, ())
        fmt_extra_sym = str(extra_targets)[1:-1] + (", ") if len(extra_targets) != 0 else ""
        with pytest.raises(ParseError) as exc:
            parser.parse(
                "dir/BUILD",
                "FAKE",
                prelude_symbols,
                EnvironmentVars({}),
                False,
                defaults_parser_state,
                dependents_rules=None,
                dependencies_rules=None,
            )
        assert str(exc.value) == softwrap(
            f"""
            dir/BUILD:1: Name 'FAKE' is not defined.

            {dym}If you expect to see more symbols activated in the below list, refer to
            {doc_url('enabling-backends')} for all available backends to activate.

            All registered symbols: [{fmt_extra_sym}'__defaults__', '__dependencies_rules__',
            '__dependents_rules__', 'build_file_dir', 'caof', 'env', 'obj', 'prelude', 'tgt']
            """
        )

        with no_exception():
            parser = Parser(
                build_root="",
                registered_target_types=RegisteredTargetTypes(
                    {alias: GenericTarget for alias in ("tgt", *extra_targets)}
                ),
                union_membership=UnionMembership({}),
                object_aliases=build_file_aliases,
                ignore_unrecognized_symbols=True,
            )
            parser.parse(
                "dir/BUILD",
                "FAKE",
                prelude_symbols,
                EnvironmentVars({}),
                False,
                defaults_parser_state,
                dependents_rules=None,
                dependencies_rules=None,
            )

    test_targs = ["FAKE1", "FAKE2", "FAKE3", "FAKE4", "FAKE5"]

    perform_test([], "")
    dym_one = "Did you mean FAKE1?\n\n"
    perform_test(test_targs[:1], dym_one)
    dym_two = "Did you mean FAKE2 or FAKE1?\n\n"
    perform_test(test_targs[:2], dym_two)
    dym_many = "Did you mean FAKE5, FAKE4, or FAKE3?\n\n"
    perform_test(test_targs, dym_many)


def test_unrecognized_symbol_during_bootstrap_issue_19156(
    defaults_parser_state: BuildFileDefaultsParserState,
) -> None:
    build_file_aliases = BuildFileAliases(
        objects={"obj": 0},
        context_aware_object_factories={"caof": lambda parse_context: lambda _: None},
    )
    parser = Parser(
        build_root="",
        registered_target_types=RegisteredTargetTypes({"tgt": GenericTarget}),
        union_membership=UnionMembership({}),
        object_aliases=build_file_aliases,
        ignore_unrecognized_symbols=True,
    )
    prelude_symbols = BuildFilePreludeSymbols.create({"prelude": 0}, ())
    target_adaptors = parser.parse(
        "dir/BUILD",
        "tgt(field=fake(42,a=(), b='c'))",
        prelude_symbols,
        EnvironmentVars({}),
        False,
        defaults_parser_state,
        dependents_rules=None,
        dependencies_rules=None,
    )

    assert len(target_adaptors) == 1
    raw_field = target_adaptors[0].kwargs["field"]
    assert repr(raw_field) == "fake(42, a=(), b='c')"

    class TestField(StringField):
        alias = "field"

    err = re.escape(
        f"The 'field' field in target // must be a string, but was `{raw_field!r}` "
        "with type `<unrecognized symbol>`."
    )
    with pytest.raises(InvalidFieldException, match=err):
        TestField(raw_field, Address(""))


def test_unknown_target_for_defaults_during_bootstrap_issue_19445(
    defaults_parser_state: BuildFileDefaultsParserState,
) -> None:
    parser = Parser(
        build_root="",
        registered_target_types=RegisteredTargetTypes({}),
        union_membership=UnionMembership({}),
        object_aliases=BuildFileAliases(),
        ignore_unrecognized_symbols=True,
    )
    parser.parse(
        "BUILD",
        "__defaults__({'type_1': dict(), type_2: dict()})",
        BuildFilePreludeSymbols.create({}, ()),
        EnvironmentVars({}),
        True,
        defaults_parser_state,
        dependents_rules=None,
        dependencies_rules=None,
    )


@pytest.mark.parametrize("symbol", ["a", "bad", "BAD", "a___b_c", "a231", "áç"])
def test_extract_symbol_from_name_error(symbol: str) -> None:
    assert _extract_symbol_from_name_error(NameError(f"name '{symbol}' is not defined")) == symbol


def test_unrecognized_symbol_in_prelude(
    defaults_parser_state: BuildFileDefaultsParserState,
) -> None:
    build_file_aliases = BuildFileAliases(
        objects={"obj": 0},
        context_aware_object_factories={"caof": lambda parse_context: lambda _: None},
    )
    parser = Parser(
        build_root="",
        registered_target_types=RegisteredTargetTypes({}),
        union_membership=UnionMembership({}),
        object_aliases=build_file_aliases,
        ignore_unrecognized_symbols=False,
    )
    prelude: dict[str, Any] = {}
    exec(
        compile(
            dedent(
                """\
                # This macro references some undefined symbol...
                def macro():
                    return NonExisting
                """
            ),
            "preludes/bad.py",
            "exec",
            dont_inherit=True,
        ),
        {},
        prelude,
    )
    prelude_symbols = BuildFilePreludeSymbols.create(prelude, ())

    with pytest.raises(ParseError) as exc:
        parser.parse(
            filepath="dir/BUILD",
            build_file_content="macro()",
            extra_symbols=prelude_symbols,
            env_vars=EnvironmentVars({}),
            is_bootstrap=False,
            defaults=defaults_parser_state,
            dependents_rules=None,
            dependencies_rules=None,
        )
    assert str(exc.value) == softwrap(
        f"""
        preludes/bad.py:3:macro: Name 'NonExisting' is not defined.

        Did you mean macro?

        If you expect to see more symbols activated in the below list, refer to
        {doc_url('enabling-backends')} for all available backends to activate.

        All registered symbols: ['__defaults__', '__dependencies_rules__', '__dependents_rules__',
        'build_file_dir', 'caof', 'env', 'macro', 'obj']
        """
    )
