# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest


from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.parser import BuildFilePreludeSymbols, ParseError, Parser
from pants.util.docutil import docs_url
from pants.util.frozendict import FrozenDict

def test_imports_banned() -> None:
    parser = Parser(target_type_aliases=[], object_aliases=BuildFileAliases())
    with pytest.raises(ParseError) as exc:
        parser.parse(
            "dir/BUILD", "\nx = 'hello'\n\nimport os\n", BuildFilePreludeSymbols(FrozenDict())
        )
    assert "Import used in dir/BUILD at line 4" in str(exc.value)


def test_unrecogonized_symbol() -> None:
    def perform_test(tta: list, good_err: str) -> None:
        parser = Parser(
            target_type_aliases=tta,
            object_aliases=BuildFileAliases(
                objects={"obj": 0},
                context_aware_object_factories={"caof": lambda parse_context: lambda _: None},
            ),
        )
        prelude_symbols = BuildFilePreludeSymbols(FrozenDict({"prelude": 0}))
        with pytest.raises(ParseError) as exc:
            parser.parse("dir/BUILD", "fake", prelude_symbols)
        assert (
            str(exc.value)
            == good_err
    )

    # confirm that it works if there's nothing similar
    no_match_tta = ["tgt"]
    no_match_str = ("Name 'fake' is not defined.\n\n"
                    "If you expect to see more symbols activated in the below list,"
                    f"refer to {docs_url('enabling_backends')} for all available"
                    " backends to activate.\n\n"
                    "All registered symbols: ['caof', 'obj', 'prelude', 'tgt']"
    )

    # confirm that "did you mean x" works
    one_match_tta = ["tgt","fake1"]
    one_match_str = ("Name 'fake' is not defined.\n\n"
                    "Did you mean fake1?\n\n"
                    "If you expect to see more symbols activated in the below list,"
                    f"refer to {docs_url('enabling_backends')} for all available"
                    " backends to activate.\n\n"
                    "All registered symbols: ['caof', 'fake1', 'obj', 'prelude', 'tgt']"
    )


    # confirm that "did you mean x or y" works
    two_match_tta = ["tgt","fake1","fake2"]
    two_match_str = ("Name 'fake' is not defined.\n\n"
                    "Did you mean fake2 or fake1?\n\n"
                    "If you expect to see more symbols activated in the below list,"
                    f"refer to {docs_url('enabling_backends')} for all available"
                    " backends to activate.\n\n"
                    "All registered symbols: ['caof', 'fake1', 'fake2', 'obj', 'prelude', 'tgt']"
    )


    # confirm that "did you mean x, y or z" works (limit to 3 match)
    many_match_tta = ["tgt","fake1","fake2","fake3","fake4","fake5"]
    many_match_str = ("Name 'fake' is not defined.\n\n"
                    "Did you mean fake5, fake4 or fake3?\n\n"
                    "If you expect to see more symbols activated in the below list,"
                    f"refer to {docs_url('enabling_backends')} for all available"
                    " backends to activate.\n\n"
                    "All registered symbols: ['caof', 'fake1', 'fake2',"
                    " 'fake3', 'fake4', 'fake5', 'obj', 'prelude', 'tgt']"
    )


    perform_test(no_match_tta,no_match_str)
    perform_test(one_match_tta,one_match_str)
    perform_test(two_match_tta,two_match_str)
    perform_test(many_match_tta,many_match_str)



