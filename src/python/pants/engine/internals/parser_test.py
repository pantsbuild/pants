# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.parser import (
    BuildFilePreludeSymbols,
    ParseError,
    Parser,
    error_on_imports_and_rewrite_caofs_to_avoid_ambiguous_symbols,
)
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict


def test_imports_banned() -> None:
    parser = Parser(build_root="", target_type_aliases=[], object_aliases=BuildFileAliases())
    with pytest.raises(ParseError) as exc:
        parser.parse(
            "dir/BUILD", "\nx = 'hello'\n\nimport os\n", BuildFilePreludeSymbols(FrozenDict())
        )
    assert "Import used in dir/BUILD at line 4" in str(exc.value)


def test_unrecognized_symbol() -> None:
    def assert_error(extra_targets: list[str], did_you_mean: str) -> None:
        parser = Parser(
            build_root="",
            target_type_aliases=["tgt", *extra_targets],
            object_aliases=BuildFileAliases(
                objects={"obj": 0},
                context_aware_object_factories={"caof": lambda parse_context: lambda _: None},
            ),
        )
        prelude_symbols = BuildFilePreludeSymbols(FrozenDict({"prelude": 0}))

        with pytest.raises(ParseError) as exc:
            parser.parse("dir/BUILD", "fake", prelude_symbols)

        fmt_extra_sym = str(extra_targets)[1:-1] + (", ") if len(extra_targets) != 0 else ""
        assert str(exc.value) == (
            f"Name 'fake' is not defined.\n\n{did_you_mean}"
            "If you expect to see more symbols activated in the below list,"
            f" refer to {doc_url('enabling-backends')} for all available"
            " backends to activate.\n\n"
            f"All registered symbols: ['caof', {fmt_extra_sym}'obj', 'prelude', 'tgt']"
        )

    extra_targets = ["fake1", "fake2", "fake3", "fake4", "fake5"]
    assert_error([], "")
    assert_error(extra_targets[:1], "Did you mean fake1?\n\n")
    assert_error(extra_targets[:2], "Did you mean fake2 or fake1?\n\n")
    assert_error(extra_targets, "Did you mean fake5, fake4, or fake3?\n\n")


def test_rewrite_macro_symbols() -> None:
    unmodified_content = dedent(
        """\
        # Target generators
        python_requirements(name="reqs")
        python_requirements(
            name="reqs",
            requirements_relpath="reqs.txt",
            module_mapping={
                "foo": ("bar",),
            }
        )
        poetry_requirements(name="gen")
        pipenv_requirements(name="pipenv")
        pants_requirement(name="pants")

        # Other
        x = 1 + 2
        python_tests(sources=x, dependencies=["foo:python_requirements"])
        """
    )
    original = (
        dedent(
            """\
            # Macros
            python_requirements()
            python_requirements(
                requirements_relpath="reqs.txt",
                module_mapping={
                    "foo": ("bar",),
                }
            )
            poetry_requirements()
            pipenv_requirements()
            pants_requirement()
            """
        )
        + unmodified_content
    )
    expected = (
        dedent(
            """\
            # Macros
            python_requirements_deprecated_macro()
            python_requirements_deprecated_macro(
                requirements_relpath="reqs.txt",
                module_mapping={
                    "foo": ("bar",),
                }
            )
            poetry_requirements_deprecated_macro()
            pipenv_requirements_deprecated_macro()
            pants_requirement_deprecated_macro()
            """
        )
        + unmodified_content
    )

    assert (
        error_on_imports_and_rewrite_caofs_to_avoid_ambiguous_symbols(
            original, "BUILD", rename_symbols=True
        )
        == expected
    )
    assert (
        error_on_imports_and_rewrite_caofs_to_avoid_ambiguous_symbols(
            original, "BUILD", rename_symbols=False
        )
        == original
    )
