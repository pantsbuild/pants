# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent
from typing import cast

import pytest

from pants.build_graph.address import BuildFileAddressRequest, MaybeAddress, ResolveError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address, AddressInput, BuildFileAddress
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.build_files import (
    AddressFamilyDir,
    BuildFileOptions,
    OptionalAddressFamily,
    evaluate_preludes,
    parse_address_family,
)
from pants.engine.internals.defaults import ParametrizeDefault
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.target_adaptor import TargetAdaptor, TargetAdaptorRequest
from pants.engine.target import (
    Dependencies,
    MultipleSourcesField,
    RegisteredTargetTypes,
    StringField,
    Tags,
    Target,
)
from pants.engine.unions import UnionMembership
from pants.testutil.rule_runner import (
    MockGet,
    QueryRule,
    RuleRunner,
    engine_error,
    run_rule_with_mocks,
)
from pants.util.frozendict import FrozenDict


def test_parse_address_family_empty() -> None:
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    optional_af = run_rule_with_mocks(
        parse_address_family,
        rule_args=[
            Parser(build_root="", target_type_aliases=[], object_aliases=BuildFileAliases()),
            BuildFileOptions(("BUILD",)),
            BuildFilePreludeSymbols(FrozenDict()),
            AddressFamilyDir("/dev/null"),
            RegisteredTargetTypes({}),
            UnionMembership({}),
        ],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_type=PathGlobs,
                mock=lambda _: DigestContents([FileContent(path="/dev/null/BUILD", content=b"")]),
            ),
            MockGet(
                output_type=OptionalAddressFamily,
                input_type=AddressFamilyDir,
                mock=lambda _: OptionalAddressFamily("/dev"),
            ),
        ],
    )
    assert optional_af.path == "/dev/null"
    assert optional_af.address_family is not None
    af = optional_af.address_family
    assert af.namespace == "/dev/null"
    assert len(af.name_to_target_adaptors) == 0


def run_prelude_parsing_rule(prelude_content: str) -> BuildFilePreludeSymbols:
    symbols = run_rule_with_mocks(
        evaluate_preludes,
        rule_args=[BuildFileOptions((), prelude_globs=("prelude",))],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_type=PathGlobs,
                mock=lambda _: DigestContents(
                    [FileContent(path="/dev/null/prelude", content=prelude_content.encode())]
                ),
            ),
        ],
    )
    return cast(BuildFilePreludeSymbols, symbols)


def test_prelude_parsing_good() -> None:
    result = run_prelude_parsing_rule("def foo(): return 1")
    assert result.symbols["foo"]() == 1


def test_prelude_parsing_syntax_error() -> None:
    with pytest.raises(
        Exception, match="Error parsing prelude file /dev/null/prelude: name 'blah' is not defined"
    ):
        run_prelude_parsing_rule("blah")


def test_prelude_parsing_illegal_import() -> None:
    prelude_content = dedent(
        """\
        import os
        def make_target():
            python_sources()
        """
    )
    with pytest.raises(
        Exception,
        match="Import used in /dev/null/prelude at line 1\\. Import statements are banned",
    ):
        run_prelude_parsing_rule(prelude_content)


def test_prelude_exceptions() -> None:
    prelude_content = dedent(
        """\
        def abort():
            raise ValueError
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    assert "ValueError" not in result.symbols
    with pytest.raises(ValueError):
        result.symbols["abort"]()


class ResolveField(StringField):
    alias = "resolve"


class MockDepsField(Dependencies):
    pass


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockTgt(Target):
    alias = "mock_tgt"
    core_fields = (MockDepsField, MockMultipleSourcesField, Tags, ResolveField)


def test_resolve_address() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(Address, [AddressInput]), QueryRule(MaybeAddress, [AddressInput])]
    )
    rule_runner.write_files({"a/b/c.txt": "", "f.txt": ""})

    def assert_is_expected(address_input: AddressInput, expected: Address) -> None:
        assert rule_runner.request(Address, [address_input]) == expected

    assert_is_expected(
        AddressInput("a/b/c.txt", description_of_origin="tests"),
        Address("a/b", target_name=None, relative_file_path="c.txt"),
    )
    assert_is_expected(
        AddressInput("a/b", description_of_origin="tests"),
        Address("a/b", target_name=None, relative_file_path=None),
    )

    assert_is_expected(
        AddressInput("a/b", target_component="c", description_of_origin="tests"),
        Address("a/b", target_name="c"),
    )
    assert_is_expected(
        AddressInput("a/b/c.txt", target_component="c", description_of_origin="tests"),
        Address("a/b", relative_file_path="c.txt", target_name="c"),
    )

    # Top-level addresses will not have a path_component, unless they are a file address.
    assert_is_expected(
        AddressInput("f.txt", target_component="original", description_of_origin="tests"),
        Address("", relative_file_path="f.txt", target_name="original"),
    )
    assert_is_expected(
        AddressInput("", target_component="t", description_of_origin="tests"),
        Address("", target_name="t"),
    )

    bad_address_input = AddressInput("a/b/fake", description_of_origin="tests")
    expected_err = "'a/b/fake' does not exist on disk"
    with engine_error(ResolveError, contains=expected_err):
        rule_runner.request(Address, [bad_address_input])
    maybe_addr = rule_runner.request(MaybeAddress, [bad_address_input])
    assert isinstance(maybe_addr.val, ResolveError)
    assert expected_err in str(maybe_addr.val)


@pytest.fixture
def target_adaptor_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(TargetAdaptor, (TargetAdaptorRequest,))],
        target_types=[MockTgt],
        objects={"parametrize": Parametrize},
    )


def test_target_adaptor_parsed_correctly(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "helloworld/dir/BUILD": dedent(
                """\
                mock_tgt(
                    fake_field=42,
                    dependencies=[
                        # Because we don't follow dependencies or even parse dependencies, this
                        # self-cycle should be fine.
                        ":dir",
                        ":sibling",
                        "helloworld/util",
                        "helloworld/util:tests",
                    ],
                    build_file_dir=f"build file's dir is: {build_file_dir()}"
                )

                mock_tgt(name='t2')
                """
            )
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.name is None
    assert target_adaptor.type_alias == "mock_tgt"
    assert target_adaptor.kwargs["dependencies"] == [
        ":dir",
        ":sibling",
        "helloworld/util",
        "helloworld/util:tests",
    ]
    # NB: TargetAdaptors do not validate what fields are valid. The Target API should error
    # when encountering this, but it's fine at this stage.
    assert target_adaptor.kwargs["fake_field"] == 42
    assert target_adaptor.kwargs["build_file_dir"] == "build file's dir is: helloworld/dir"

    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [
            TargetAdaptorRequest(
                Address("helloworld/dir", target_name="t2"), description_of_origin="tests"
            )
        ],
    )
    assert target_adaptor.name == "t2"
    assert target_adaptor.type_alias == "mock_tgt"


def test_target_adaptor_defaults_applied(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "helloworld/dir/BUILD": dedent(
                """\
                __defaults__({mock_tgt: dict(resolve="mock")}, all=dict(tags=["24"]))
                mock_tgt(tags=["42"])
                mock_tgt(name='t2')
                """
            )
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.name is None
    assert target_adaptor.kwargs["resolve"] == "mock"
    assert target_adaptor.kwargs["tags"] == ["42"]

    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [
            TargetAdaptorRequest(
                Address("helloworld/dir", target_name="t2"), description_of_origin="tests"
            )
        ],
    )
    assert target_adaptor.name == "t2"
    assert target_adaptor.kwargs["resolve"] == "mock"

    # The defaults are not frozen until after the BUILD file have been fully parsed, so this is a
    # list rather than a tuple at this time.
    assert target_adaptor.kwargs["tags"] == ["24"]


def test_inherit_defaults(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "BUILD": """__defaults__(all=dict(tags=["root"]))""",
            "helloworld/dir/BUILD": dedent(
                """\
                __defaults__({mock_tgt: dict(resolve="mock")}, extend=True)
                mock_tgt()
                """
            ),
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.name is None
    assert target_adaptor.kwargs["resolve"] == "mock"

    # The defaults originates from a parent BUILD file, and as such has been frozen.
    assert target_adaptor.kwargs["tags"] == ("root",)


def test_parametrize_defaults(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                __defaults__(
                  all=dict(
                    tags=parametrize(a=["a", "root"], b=["non-root", "b"])
                  )
                )
                """
            ),
            "helloworld/dir/BUILD": "mock_tgt()",
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.kwargs["tags"] == ParametrizeDefault(a=("a", "root"), b=("non-root", "b"))


def test_target_adaptor_not_found(target_adaptor_rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        target_adaptor_rule_runner.request(
            TargetAdaptor,
            [TargetAdaptorRequest(Address("helloworld"), description_of_origin="tests")],
        )
    assert "Directory \\'helloworld\\' does not contain any BUILD files" in str(exc)

    target_adaptor_rule_runner.write_files({"helloworld/BUILD": "mock_tgt(name='other_tgt')"})
    expected_rx_str = re.escape(
        "The target name ':helloworld' is not defined in the directory helloworld"
    )
    with pytest.raises(ExecutionError, match=expected_rx_str):
        target_adaptor_rule_runner.request(
            TargetAdaptor,
            [TargetAdaptorRequest(Address("helloworld"), description_of_origin="tests")],
        )


def test_build_file_address() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(BuildFileAddress, [BuildFileAddressRequest])], target_types=[MockTgt]
    )
    rule_runner.write_files({"helloworld/BUILD.ext": "mock_tgt()"})

    def assert_bfa_resolved(address: Address) -> None:
        expected_bfa = BuildFileAddress(address, "helloworld/BUILD.ext")
        bfa = rule_runner.request(
            BuildFileAddress, [BuildFileAddressRequest(address, description_of_origin="tests")]
        )
        assert bfa == expected_bfa

    assert_bfa_resolved(Address("helloworld"))
    # Generated targets should use their target generator's BUILD file.
    assert_bfa_resolved(Address("helloworld", generated_name="f.txt"))
    assert_bfa_resolved(Address("helloworld", relative_file_path="f.txt"))


def test_build_files_share_globals() -> None:
    """Test that a macro in a prelude can reference another macro in another prelude.

    At some point a change was made to separate the globals/locals dict (uninentional) which has the
    unintended side-effect of having the `__globals__` of a macro not contain references to every
    other symbol in every other prelude.
    """

    symbols = run_rule_with_mocks(
        evaluate_preludes,
        rule_args=[BuildFileOptions((), prelude_globs=("prelude",))],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_type=PathGlobs,
                mock=lambda _: DigestContents(
                    [
                        FileContent(
                            path="/dev/null/prelude1",
                            content=dedent(
                                """\
                                def hello():
                                    pass
                                """
                            ).encode(),
                        ),
                        FileContent(
                            path="/dev/null/prelude2",
                            content=dedent(
                                """\
                                def world():
                                    pass
                                """
                            ).encode(),
                        ),
                    ]
                ),
            ),
        ],
    )
    assert symbols.symbols["hello"].__globals__ is symbols.symbols["world"].__globals__
    assert "world" in symbols.symbols["hello"].__globals__
    assert "hello" in symbols.symbols["world"].__globals__
